"""
MySQL ↔ Qdrant 对账脚本

定期核对 MySQL 商品表与 Qdrant item_style collection 的一致性，
发现并修复 MQ 消息丢失 / 消费失败 / 类目变更未同步等数据漂移问题。

对账维度：
  1. 缺失（MySQL 有 / Qdrant 无）→ MQ 消息丢失或消费失败，可选 backfill
  2. 多余（Qdrant 有 / MySQL 无或下架或缺货）→ 应清理，可选 delete
  3. 不一致（payload 字段与 MySQL 不一致，如 stock/price/color/season）→ 可选 update_payload

用法：
    cd ai-outfit
    python -m scripts.reconcile_mysql_qdrant                          # 仅检查，输出报告
    python -m scripts.reconcile_mysql_qdrant --fix-missing             # 修复缺失（重新入库）
    python -m scripts.reconcile_mysql_qdrant --fix-stale               # 修复多余（软删除）
    python -m scripts.reconcile_mysql_qdrant --fix-inconsistent        # 修复字段不一致
    python -m scripts.reconcile_mysql_qdrant --fix-all                 # 修复全部
    python -m scripts.reconcile_mysql_qdrant --report-path report.json # 报告落盘

定时执行建议：
    crontab: 0 3 * * * cd /path/to/ai-outfit && python -m scripts.reconcile_mysql_qdrant --fix-all
"""
import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from typing import Any

# 项目根目录（zmall-ai）加入 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import create_engine, text, bindparam  # noqa: E402
from qdrant_client.http.models import Filter  # noqa: E402

from shared.qdrant_client.client import QdrantClientWrapper, COLLECTION_ITEM_STYLE  # noqa: E402
from shared.qdrant_client.indexer import QdrantIndexer  # noqa: E402
from shared.qdrant_client.category_mapping import CN_TO_EN, to_en  # noqa: E402
from shared.model_client.embed_client import EmbedClient  # noqa: E402
from app.core.config import settings  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("reconcile")

OUTFIT_CATEGORIES_CN_LIST = list(CN_TO_EN.keys())


def _parse_style_tags(raw: Any) -> list[str]:
    """将 MySQL 中存储的 style_tags（JSON 文本字符串）解析为 list[str]。

    与 index_items.py 的解析逻辑保持一致：
    - None / 空 → []
    - JSON 字符串如 '["通勤","休闲"]' → ["通勤","休闲"]
    - 已是 list → 直接返回
    - 解析失败 → 返回 []
    """
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(s) for s in raw]
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(s) for s in parsed]
        except (ValueError, TypeError):
            pass
    return []


# ============================================================================
# MySQL 侧：拉取穿搭类目商品的"真相"数据
# ============================================================================

def fetch_mysql_truth() -> dict[int, dict]:
    """从 MySQL 拉取所有穿搭类目商品（含下架/缺货），返回 {itemId: {...}} 字典

    对账需要完整的"真相集"，所以不区分 status/stock，全部拉取后由对账逻辑判断。
    color/season/style_tags 均存文本值，直接取 spu_attr_value.value，无需 JOIN attribute_value。
    """
    url = (
        f"mysql+pymysql://{settings.mysql_username}:{settings.mysql_password}"
        f"@{settings.mysql_host}:{settings.mysql_port}/{settings.mysql_database}?charset=utf8mb4"
    )
    engine = create_engine(url, pool_pre_ping=True)

    sql = text(
        "SELECT i.id, i.name, i.image, i.category, i.price, i.stock, i.status, i.creater, "
        "i.target_gender AS target_gender, "
        "cv.value AS color, sv.value AS season, st_sav.value AS style_tags "
        "FROM item i "
        "LEFT JOIN spu_attr_value cv ON cv.spu_id = i.id AND cv.attribute_id = 1 "
        "LEFT JOIN spu_attr_value sv ON sv.spu_id = i.id AND sv.attribute_id = 4 "
        "LEFT JOIN spu_attr_value st_sav ON st_sav.spu_id = i.id AND st_sav.attribute_id = 5 "
        "WHERE i.category IN :categories "
        "ORDER BY i.id"
    ).bindparams(bindparam("categories", expanding=True))

    result_map: dict[int, dict] = {}
    with engine.connect() as conn:
        result = conn.execute(sql, {"categories": tuple(OUTFIT_CATEGORIES_CN_LIST)})
        for row in result.mappings():
            item_id = int(row["id"])
            # target_gender 规范化：仅接受 male/female/unisex，其他视为 None
            raw_gender = row.get("target_gender")
            target_gender = raw_gender if raw_gender in ("male", "female", "unisex") else None
            result_map[item_id] = {
                "id": item_id,
                "name": row["name"],
                "image": row["image"],
                "category_cn": row["category"],  # 中文
                "category_en": to_en(row["category"]),  # 英文（Qdrant payload 应该是这个）
                "price": float(row["price"] or 0),
                "stock": int(row["stock"] or 0),
                "color": row.get("color"),
                "season": row.get("season"),
                "style_tags": row.get("style_tags"),
                "target_gender": target_gender,
                "status": int(row["status"]),
                "is_active": (row["status"] == 1),
                "creater": int(row["creater"] or 0),
            }
    engine.dispose()
    logger.info("MySQL 真相集: %d 件穿搭类目商品", len(result_map))
    return result_map


# ============================================================================
# Qdrant 侧：scroll 拉取所有 point
# ============================================================================

def fetch_qdrant_state(qdrant_wrapper: QdrantClientWrapper) -> dict[int, dict]:
    """从 Qdrant scroll 全量拉取 item_style collection 的所有 point

    返回 {itemId: {payload...}} 字典。
    """
    client = qdrant_wrapper.get_client()
    qdrant_map: dict[int, dict] = {}

    offset = None
    while True:
        # scroll 一次拉 256 条
        result = client.scroll(
            collection_name=COLLECTION_ITEM_STYLE,
            scroll_filter=Filter(),  # 空 filter，全量
            limit=256,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        if not result[0]:
            break
        for point in result[0]:
            payload = point.payload or {}
            item_id = payload.get("item_id")
            if item_id is None:
                # 兜底：旧版 point id 是 "item_123" 字符串格式，新版是整数
                try:
                    item_id = int(str(point.id).replace("item_", ""))
                except Exception:
                    logger.warning("Qdrant point 无法解析 itemId: pointId=%s", point.id)
                    continue
            qdrant_map[int(item_id)] = {
                "item_id": int(item_id),
                "shop_id": payload.get("shop_id"),
                "category": payload.get("category"),  # 英文枚举
                "style_tags": payload.get("style_tags", []),
                "price": payload.get("price"),
                "stock": payload.get("stock", 0),
                "color": payload.get("color"),
                "season": payload.get("season"),
                "target_gender": payload.get("target_gender"),
                "is_active": payload.get("is_active", True),
            }
        offset = result[1]  # 下一页 offset
        if offset is None:
            break

    logger.info("Qdrant 状态集: %d 个 point", len(qdrant_map))
    return qdrant_map


# ============================================================================
# 对账核心
# ============================================================================

def reconcile(
    mysql_truth: dict[int, dict],
    qdrant_state: dict[int, dict],
) -> dict[str, Any]:
    """对账主逻辑

    三类不一致：
      - missing: MySQL 有 / Qdrant 无 → 需重新入库
      - stale:   Qdrant 有 / MySQL 无（或 MySQL 类目已改为非穿搭）→ 需删除
      - inconsistent: 两边都有但 payload 字段不一致 → 需 update_payload

    Returns:
        对账报告 dict
    """
    mysql_ids = set(mysql_truth.keys())
    qdrant_ids = set(qdrant_state.keys())

    missing_ids = sorted(mysql_ids - qdrant_ids)
    stale_ids = sorted(qdrant_ids - mysql_ids)
    common_ids = sorted(mysql_ids & qdrant_ids)

    # 字段不一致检测（仅检测 common_ids）
    inconsistent: list[dict] = []
    for item_id in common_ids:
        m = mysql_truth[item_id]
        q = qdrant_state[item_id]

        diffs: dict[str, dict] = {}

        # is_active: MySQL status=1 → True，其他 → False；Qdrant is_active 字段
        expected_active = m["is_active"]
        if q["is_active"] != expected_active:
            diffs["is_active"] = {"mysql": expected_active, "qdrant": q["is_active"]}

        # stock
        expected_stock = m["stock"]
        if q["stock"] != expected_stock:
            diffs["stock"] = {"mysql": expected_stock, "qdrant": q["stock"]}

        # price
        expected_price = m["price"]
        if q["price"] != expected_price:
            diffs["price"] = {"mysql": expected_price, "qdrant": q["price"]}

        # category（Qdrant 存英文，MySQL 存中文 → 转 英文 后比较）
        expected_cat_en = m["category_en"]
        if q["category"] != expected_cat_en:
            diffs["category"] = {"mysql_en": expected_cat_en, "qdrant": q["category"]}

        # color（None 与 缺失字段 都视为"无"）
        expected_color = m["color"]
        if (q["color"] or None) != (expected_color or None):
            diffs["color"] = {"mysql": expected_color, "qdrant": q["color"]}

        # season
        expected_season = m["season"]
        if (q["season"] or None) != (expected_season or None):
            diffs["season"] = {"mysql": expected_season, "qdrant": q["season"]}

        # target_gender（None 与 缺失字段 都视为"无"）
        expected_gender = m["target_gender"]
        if (q["target_gender"] or None) != (expected_gender or None):
            diffs["target_gender"] = {"mysql": expected_gender, "qdrant": q["target_gender"]}

        # style_tags（MySQL 存 JSON 文本字符串，Qdrant 存 list[str]）
        expected_style_tags = _parse_style_tags(m["style_tags"])
        q_style_tags = q.get("style_tags") or []
        if q_style_tags != expected_style_tags:
            diffs["style_tags"] = {"mysql": expected_style_tags, "qdrant": q_style_tags}

        if diffs:
            inconsistent.append({"item_id": item_id, "diffs": diffs})

    report = {
        "summary": {
            "mysql_total": len(mysql_truth),
            "qdrant_total": len(qdrant_state),
            "missing_count": len(missing_ids),
            "stale_count": len(stale_ids),
            "inconsistent_count": len(inconsistent),
            "consistent_count": len(common_ids) - len(inconsistent),
        },
        "missing_ids": missing_ids,
        "stale_ids": stale_ids,
        "inconsistent": inconsistent,
    }
    return report


# ============================================================================
# 修复操作
# ============================================================================

def _build_reconcile_item_text(item: dict) -> str:
    """拼接商品文本用于向量编码（纯文本向量模式）

    与 index_items.py 的 build_item_text 逻辑一致：
    拼接 name + category + color + season + style_tags
    """
    parts = []
    name = item.get("name")
    if name:
        parts.append(str(name).strip())
    category = item.get("category_cn") or item.get("category")
    if category:
        parts.append(str(category).strip())
    color = item.get("color")
    if color:
        parts.append(str(color).strip())
    season = item.get("season")
    if season:
        parts.append(str(season).strip())
    style_tags = _parse_style_tags(item.get("style_tags"))
    if style_tags:
        parts.extend(style_tags)
    return " ".join(parts) if parts else ""


async def fix_missing(
    missing_ids: list[int],
    mysql_truth: dict[int, dict],
    indexer: QdrantIndexer,
    embed_client: EmbedClient,
) -> tuple[int, int]:
    """修复缺失商品：拼接文本 + encode_text + upsert

    纯文本向量模式：用商品文本属性（name+category+color+season+style_tags）
    编码为向量后写入 Qdrant，与 index_items.py 入库逻辑一致。

    Returns: (success_count, fail_count)
    """
    success = 0
    fail = 0
    for i, item_id in enumerate(missing_ids):
        item = mysql_truth[item_id]
        # 仅上架且有库存的才 backfill，下架或缺货的暂不处理（避免无效 encode）
        if not item["is_active"] or item["stock"] <= 0:
            logger.debug("缺失商品但下架/缺货，跳过 backfill: itemId=%s, status=%s, stock=%s",
                          item_id, item["status"], item["stock"])
            continue

        item_text = _build_reconcile_item_text(item)
        if not item_text:
            logger.warning("缺失商品文本为空，跳过: itemId=%s", item_id)
            fail += 1
            continue

        try:
            vector = await embed_client.encode_text(item_text)
            if vector is None or len(vector) != 1024:
                logger.warning("缺失商品 encode 失败: itemId=%s, text=%s", item_id, item_text[:80])
                fail += 1
                continue

            indexer.upsert_item(
                item_id=item_id,
                vector=vector,
                shop_id=item["creater"],
                category=item["category_en"],
                style_tags=_parse_style_tags(item["style_tags"]),
                price=item["price"],
                color=item["color"],
                season=item["season"],
                stock=item["stock"],
                is_active=True,
                target_gender=item.get("target_gender"),
            )
            success += 1
        except Exception as e:
            logger.error("缺失商品 backfill 异常: itemId=%s, error=%s", item_id, e, exc_info=True)
            fail += 1

        if (i + 1) % 20 == 0:
            logger.info("fix-missing 进度: %d/%d (成功 %d, 失败 %d)",
                         i + 1, len(missing_ids), success, fail)

    return success, fail


def fix_stale(
    stale_ids: list[int],
    indexer: QdrantIndexer,
) -> int:
    """修复多余商品：从 Qdrant 软删除（set is_active=false，保留向量供对账复查）

    Returns: 已处理数量
    """
    count = 0
    for item_id in stale_ids:
        try:
            indexer.set_item_inactive(item_id)
            count += 1
        except Exception as e:
            logger.error("stale 软删除失败: itemId=%s, error=%s", item_id, e)
    return count


def fix_inconsistent(
    inconsistent: list[dict],
    mysql_truth: dict[int, dict],
    indexer: QdrantIndexer,
) -> int:
    """修复字段不一致：调 update_payload（保留向量，省 encode API）

    仅当图片未变更时才走 update_payload；如果 is_active 字段不一致属于状态变更，也走 update_payload。

    Returns: 已修复数量
    """
    count = 0
    for entry in inconsistent:
        item_id = entry["item_id"]
        item = mysql_truth[item_id]

        try:
            indexer.update_payload(
                item_id=item_id,
                shop_id=item["creater"],
                category=item["category_en"],
                style_tags=_parse_style_tags(item["style_tags"]),
                price=item["price"],
                color=item["color"],
                season=item["season"],
                stock=item["stock"],
                is_active=item["is_active"],
                target_gender=item.get("target_gender"),
            )
            count += 1
        except Exception as e:
            logger.error("不一致修复失败: itemId=%s, error=%s", item_id, e)
    return count


# ============================================================================
# 主入口
# ============================================================================

async def main():
    parser = argparse.ArgumentParser(description="MySQL ↔ Qdrant 对账脚本")
    parser.add_argument("--fix-missing", action="store_true",
                        help="修复缺失商品（MySQL 有 / Qdrant 无）")
    parser.add_argument("--fix-stale", action="store_true",
                        help="修复多余商品（Qdrant 有 / MySQL 无，软删除）")
    parser.add_argument("--fix-inconsistent", action="store_true",
                        help="修复字段不一致（update_payload）")
    parser.add_argument("--fix-all", action="store_true",
                        help="等价于 --fix-missing --fix-stale --fix-inconsistent")
    parser.add_argument("--report-path", default=None,
                        help="对账报告 JSON 落盘路径（不指定则仅打印）")
    args = parser.parse_args()

    fix_missing_flag = args.fix_missing or args.fix_all
    fix_stale_flag = args.fix_stale or args.fix_all
    fix_inconsistent_flag = args.fix_inconsistent or args.fix_all

    logger.info("==== MySQL ↔ Qdrant 对账开始 ====")
    logger.info("时间: %s", datetime.now().isoformat())
    logger.info("修复开关: missing=%s, stale=%s, inconsistent=%s",
                fix_missing_flag, fix_stale_flag, fix_inconsistent_flag)

    # 1. 拉取两侧数据
    mysql_truth = fetch_mysql_truth()

    qdrant_wrapper = QdrantClientWrapper(
        host=settings.qdrant_host,
        port=settings.qdrant_port,
        api_key=settings.qdrant_api_key,
        prefix=settings.qdrant_prefix,
        proxy_url=settings.proxy_url,
    )
    qdrant_wrapper.ensure_collections()
    indexer = QdrantIndexer(qdrant_wrapper)
    qdrant_state = fetch_qdrant_state(qdrant_wrapper)

    # 2. 对账
    report = reconcile(mysql_truth, qdrant_state)
    s = report["summary"]
    logger.info("==== 对账结果 ====")
    logger.info("MySQL 穿搭商品: %d 件", s["mysql_total"])
    logger.info("Qdrant point:    %d 个", s["qdrant_total"])
    logger.info("缺失(MySQL有/Qdrant无):     %d 件", s["missing_count"])
    logger.info("多余(Qdrant有/MySQL无):     %d 件", s["stale_count"])
    logger.info("字段不一致:                  %d 件", s["inconsistent_count"])
    logger.info("完全一致:                    %d 件", s["consistent_count"])

    if args.report_path:
        with open(args.report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2, default=str)
        logger.info("对账报告已落盘: %s", args.report_path)

    # 3. 修复
    fix_stats: dict[str, Any] = {}

    if fix_missing_flag and report["missing_ids"]:
        embed_client = EmbedClient(
            api_url=settings.embed_api_url,
            api_key=settings.embed_api_key,
        )
        try:
            logger.info("==== 修复缺失商品: %d 件 ====", len(report["missing_ids"]))
            success, fail = await fix_missing(
                report["missing_ids"], mysql_truth, indexer, embed_client
            )
            fix_stats["fix_missing"] = {"success": success, "fail": fail}
            logger.info("fix-missing 完成: 成功 %d, 失败 %d", success, fail)
        finally:
            await embed_client.close()

    if fix_stale_flag and report["stale_ids"]:
        logger.info("==== 修复多余商品: %d 件（软删除）====", len(report["stale_ids"]))
        count = fix_stale(report["stale_ids"], indexer)
        fix_stats["fix_stale"] = {"deleted": count}
        logger.info("fix-stale 完成: 软删除 %d 件", count)

    if fix_inconsistent_flag and report["inconsistent"]:
        logger.info("==== 修复字段不一致: %d 件（update_payload）====", len(report["inconsistent"]))
        count = fix_inconsistent(report["inconsistent"], mysql_truth, indexer)
        fix_stats["fix_inconsistent"] = {"updated": count}
        logger.info("fix-inconsistent 完成: 更新 %d 件", count)

    if fix_stats:
        logger.info("==== 修复汇总 ====")
        for op, stat in fix_stats.items():
            logger.info("%s: %s", op, stat)
    else:
        logger.info("未启用任何修复开关（仅检查），如需修复请加 --fix-missing / --fix-stale / --fix-inconsistent / --fix-all")

    logger.info("==== 对账结束 ====")


if __name__ == "__main__":
    asyncio.run(main())

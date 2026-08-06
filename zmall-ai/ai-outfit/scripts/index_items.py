"""
商品向量全量入库脚本（ai-outfit 版，纯文本向量模式）

从 MySQL（默认）或 Java item-service 分页拉取上架商品，对穿搭类目商品
（上衣/下装/鞋/帽子/包/配饰）拼接文本（名称+类目+颜色+季节+风格）后
进行向量编码，写入 Qdrant。

文本拼接策略："{name} {category} {color} {season} {style_tags}"
商品文本属性已足够支撑语义检索。

用法（用户手动运行）:
    cd ai-outfit
    python -m scripts.index_items                          # 全量入库（MySQL 直连，默认）
    python -m scripts.index_items --item-id 123            # 单个商品入库
    python -m scripts.index_items --shop-id 1001           # 指定店铺入库
    python -m scripts.index_items --source java            # 走 Java item-service HTTP
    python -m scripts.index_items --dry-run                # 仅打印不写 Qdrant
    python -m scripts.index_items --include-out-of-stock   # 包含库存=0 商品（默认过滤）

依赖：
    sqlalchemy + pymysql（MySQL 直连模式）
    httpx（Java HTTP 模式）
    shared.qdrant_client（QdrantIndexer）
    shared.model_client.embed_client（EmbedClient）
"""
import argparse
import asyncio
import logging
import os
import sys

# 将项目根目录（zmall-ai）加入 sys.path，使 shared 包可被导入
# 文件路径：zmall-ai/ai-outfit/scripts/index_items.py → 3 次 dirname 到 zmall-ai
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import httpx  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from shared.qdrant_client.client import QdrantClientWrapper, COLLECTION_ITEM_STYLE  # noqa: E402
from shared.qdrant_client.indexer import QdrantIndexer  # noqa: E402
from shared.qdrant_client.category_mapping import CN_TO_EN, to_en  # noqa: E402
from shared.model_client.embed_client import EmbedClient  # noqa: E402
from app.core.config import settings  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("index_items")

# 穿搭类目中文名列表（用于 MySQL WHERE IN 过滤，单一真相源在 category_mapping.py）
OUTFIT_CATEGORIES_CN_LIST = list(CN_TO_EN.keys())


# ============================================================================
# 数据源 1：MySQL 直连（默认，高效，SQL 层做穿搭类目过滤）
# ============================================================================

def fetch_items_from_mysql(
    shop_id: int | None = None,
    include_out_of_stock: bool = False,
    min_id: int | None = None,
    max_id: int | None = None,
) -> list[dict]:
    """从 MySQL 直接拉取穿搭类目商品

    SQL 层做类目过滤，避免拉取全量 88k 商品后再过滤。
    item 表已移除 color/season/style_tags/sizes/material 冗余字段，改用 EAV 模型存储：
    - color 从 spu_attr_value 获取（attribute_id=1，存文本值如 '白色'）
    - season 从 spu_attr_value 获取（attribute_id=4，存文本值如 'summer'）
    - style_tags 从 spu_attr_value 获取（attribute_id=5，存 JSON 数组文本）

    Args:
        shop_id: 仅拉取指定店铺（creater = shop_id）的商品
        include_out_of_stock: 是否包含库存=0 的商品（默认过滤）
        min_id: 仅拉取 id >= min_id 的商品
        max_id: 仅拉取 id <= max_id 的商品（与 min_id 配合做范围过滤）
    """
    url = (
        f"mysql+pymysql://{settings.mysql_username}:{settings.mysql_password}"
        f"@{settings.mysql_host}:{settings.mysql_port}/{settings.mysql_database}?charset=utf8mb4"
    )
    engine = create_engine(url, pool_pre_ping=True)

    # 动态构造 WHERE 条件
    conditions = ["i.category IN :categories"]
    params: dict = {"categories": tuple(OUTFIT_CATEGORIES_CN_LIST)}
    if not include_out_of_stock:
        conditions.append("i.stock > 0")
    if shop_id is not None:
        conditions.append("i.creater = :shop_id")
        params["shop_id"] = shop_id
    if min_id is not None:
        conditions.append("i.id >= :min_id")
        params["min_id"] = min_id
    if max_id is not None:
        conditions.append("i.id <= :max_id")
        params["max_id"] = max_id
    # 只拉上架商品（status=1）
    conditions.append("i.status = 1")

    # EAV JOIN：color/season/style_tags 均存文本值，直接取 spu_attr_value.value
    # target_gender 直接从 item 表读（已存在字段，male/female/unisex）
    sql = text(
        "SELECT i.id, i.name, i.image, i.category, i.price, i.stock, i.status, i.creater, "
        "i.target_gender AS target_gender, "
        "cv.value AS color, sv.value AS season, st_sav.value AS style_tags "
        "FROM item i "
        "LEFT JOIN spu_attr_value cv ON cv.spu_id = i.id AND cv.attribute_id = 1 "
        "LEFT JOIN spu_attr_value sv ON sv.spu_id = i.id AND sv.attribute_id = 4 "
        "LEFT JOIN spu_attr_value st_sav ON st_sav.spu_id = i.id AND st_sav.attribute_id = 5 "
        "WHERE " + " AND ".join(conditions) +
        " ORDER BY i.id"
    )

    with engine.connect() as conn:
        # SQLAlchemy text 不直接支持 tuple IN，需用 expanding bindparam
        from sqlalchemy import bindparam
        sql = sql.bindparams(bindparam("categories", expanding=True))
        result = conn.execute(sql, params)
        items = []
        for row in result.mappings():
            items.append({
                "id": row["id"],
                "name": row["name"],
                "image": row["image"],
                "category": row["category"],
                "price": row["price"],
                "stock": row["stock"],
                "color": row.get("color"),
                "season": row.get("season"),
                "style_tags": row.get("style_tags"),
                "target_gender": row.get("target_gender"),
                "status": row["status"],
                "creater": row["creater"],
            })
    engine.dispose()
    logger.info("MySQL 拉取完成: %d 件穿搭类目商品 (shopId=%s, includeOutOfStock=%s)",
                len(items), shop_id, include_out_of_stock)
    return items


def fetch_single_item_from_mysql(item_id: int) -> dict | None:
    """从 MySQL 拉取单个商品（按 ID）"""
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
        "WHERE i.id = :id"
    )
    with engine.connect() as conn:
        result = conn.execute(sql, {"id": item_id})
        row = result.mappings().first()
    engine.dispose()
    return dict(row) if row is not None else None


# ============================================================================
# 数据源 2：Java item-service HTTP（备选，无 MySQL 直连权限时用）
# ============================================================================

async def fetch_items_from_java(item_service_url: str, shop_id: int | None = None) -> list[dict]:
    """从 Java item-service 分页拉取全部上架商品（HTTP 模式）

    Java /items/page 不支持类目过滤，需客户端过滤。
    """
    items: list[dict] = []
    page_no = 1
    page_size = 100
    skipped_non_outfit = 0

    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            resp = await client.get(
                f"{item_service_url}/items/page",
                params={"pageNo": page_no, "pageSize": page_size},
            )
            if resp.status_code != 200:
                logger.error("拉取商品失败: status=%s, body=%s", resp.status_code, resp.text)
                break

            data = resp.json()
            page_items = data.get("list", [])
            total = data.get("total", 0)

            for item in page_items:
                if item.get("status") != 1:
                    continue
                if shop_id is not None and item.get("creater") != shop_id:
                    continue
                # 穿搭类目过滤（Java HTTP 模式同样需要）
                if item.get("category") not in CN_TO_EN:
                    skipped_non_outfit += 1
                    continue
                items.append(item)

            logger.info("已拉取第 %d 页, 累计穿搭商品 %d 件 (跳过非穿搭 %d 件, total=%d)",
                         page_no, len(items), skipped_non_outfit, total)

            if len(page_items) < page_size or page_no * page_size >= total:
                break
            page_no += 1

    return items


async def fetch_single_item_from_java(item_service_url: str, item_id: int) -> dict | None:
    """从 Java item-service 拉取单个商品详情"""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{item_service_url}/items/{item_id}")
        if resp.status_code != 200:
            logger.error("拉取商品 %s 失败: status=%s", item_id, resp.status_code)
            return None
        return resp.json()


# ============================================================================
# 入库核心逻辑（含 3 项修复）
# ============================================================================

def build_item_text(item: dict) -> str:
    """拼接商品文本用于向量编码

    纯文本向量模式下，商品入库时需要把文本属性拼接成一段文本，
    用 text-embedding-v4 编码为向量，写入 Qdrant。

    文本拼接策略（按重要性排序）：
      {name} {category} {color} {season} {style_tags}

    例如：
      "粉色半身裙 女装 韩版气质款 下装 粉色 summer 韩版 气质"

    Args:
        item: 商品字典，包含 name/category/color/season/style_tags 等字段
    Returns:
        拼接后的文本字符串
    """
    parts = []

    # 商品名称（最核心的文本，通常含丰富描述）
    name = item.get("name")
    if name:
        parts.append(name.strip())

    # 类目（中文）
    category = item.get("category")
    if category:
        parts.append(category.strip())

    # 颜色
    color = item.get("color")
    if color:
        parts.append(color.strip())

    # 季节
    season = item.get("season")
    if season:
        parts.append(season.strip())

    # 风格标签（可能是 JSON 数组文本，也可能是 list）
    raw_style = item.get("style_tags")
    if raw_style:
        try:
            import json as _json
            if isinstance(raw_style, str):
                parsed = _json.loads(raw_style)
                if isinstance(parsed, list):
                    style_tags = [str(s) for s in parsed if s]
                else:
                    style_tags = [str(parsed)]
            elif isinstance(raw_style, list):
                style_tags = [str(s) for s in raw_style if s]
            else:
                style_tags = []
            if style_tags:
                parts.extend(style_tags)
        except (ValueError, TypeError):
            pass

    # 兜底：如果所有字段都为空，用一个默认文本避免编码失败
    if not parts:
        return f"商品{item.get('id', '')}"

    return " ".join(parts)


async def index_item(
    indexer: QdrantIndexer,
    embed_client: EmbedClient,
    item: dict,
    dry_run: bool = False,
) -> bool:
    """将单个商品编码并写入 Qdrant

    纯文本向量模式：
      1. 拼接商品文本（名称+类目+颜色+季节+风格）
      2. 用 text-embedding-v4 编码为向量
      3. 写入 Qdrant

    Returns:
        True 表示成功入库
    """
    item_id = item.get("id")
    category_cn = item.get("category")

    # 防御性校验：非穿搭类目直接跳过
    if category_cn not in CN_TO_EN:
        logger.debug("非穿搭类目跳过: itemId=%s, category=%s", item_id, category_cn)
        return False

    # 拼接商品文本
    item_text = build_item_text(item)
    if not item_text:
        logger.warning("跳过商品 %s: 文本拼接为空", item_id)
        return False

    if dry_run:
        logger.info("[DRY-RUN] 将入库: itemId=%s, category=%s, color=%s, season=%s, stock=%s, target_gender=%s, text=%s",
                     item_id, category_cn, item.get("color"), item.get("season"),
                     item.get("stock"), item.get("target_gender"), item_text[:80])
        return True

    # 编码文本为向量
    vector = await embed_client.encode_text(item_text)
    if vector is None or len(vector) != 1024:
        logger.warning("跳过商品 %s: 向量编码失败 (api_url=%s, text=%s)",
                        item_id, embed_client.api_url, item_text[:80])
        return False

    # 品类中→英转码
    category_en = to_en(category_cn)

    # 解析风格标签 JSON（EAV 表 spu_attr_value.attribute_id=5 存 JSON 数组文本）
    import json as _json
    style_tags: list[str] = []
    raw_style = item.get("style_tags")
    if raw_style:
        try:
            parsed = _json.loads(raw_style) if isinstance(raw_style, str) else raw_style
            if isinstance(parsed, list):
                style_tags = [str(s) for s in parsed]
        except (ValueError, TypeError):
            logger.debug("风格标签 JSON 解析失败，使用空列表: itemId=%s, raw=%s", item_id, raw_style)

    # 性别过滤扩展（2026-07-27）：从 item 表 target_gender 字段读，写入 Qdrant payload
    raw_gender = item.get("target_gender")
    target_gender: str | None = None
    if raw_gender in ("male", "female", "unisex"):
        target_gender = raw_gender
    elif raw_gender:
        logger.debug("target_gender 非法值，置为 None: itemId=%s, raw=%s", item_id, raw_gender)

    # 传 color/season/stock/style_tags/target_gender 到 Qdrant
    indexer.upsert_item(
        item_id=int(item_id),
        vector=vector,
        shop_id=int(item.get("creater") or 0),
        category=category_en,
        style_tags=style_tags,
        price=float(item.get("price") or 0),
        color=item.get("color") or None,
        season=item.get("season") or None,
        stock=int(item.get("stock") or 0),
        is_active=(item.get("status") == 1),
        target_gender=target_gender,
    )
    return True


# ============================================================================
# 主入口
# ============================================================================

async def main():
    parser = argparse.ArgumentParser(description="Qdrant 商品向量全量入库（穿搭类目过滤版）")
    parser.add_argument("--source", choices=["mysql", "java"], default="mysql",
                        help="数据源：mysql（默认，SQL 层类目过滤）或 java（HTTP 分页）")
    parser.add_argument("--item-service-url", default="http://192.168.59.128:8081",
                        help="Java item-service 地址（--source java 时使用）")
    parser.add_argument("--item-id", type=int, default=None,
                        help="仅入库指定商品ID（单条模式）")
    parser.add_argument("--shop-id", type=int, default=None,
                        help="仅入库指定店铺的商品")
    parser.add_argument("--dry-run", action="store_true",
                        help="仅打印不写 Qdrant（用于核对过滤结果）")
    parser.add_argument("--include-out-of-stock", action="store_true",
                        help="包含库存=0 的商品（默认过滤，仅 MySQL 源生效）")
    parser.add_argument("--min-id", type=int, default=None,
                        help="仅入库 id >= min_id 的商品（需配合 --max-id 精确过滤）")
    parser.add_argument("--max-id", type=int, default=None,
                        help="仅入库 id <= max_id 的商品（如 --min-id 200001 --max-id 200060）")
    parser.add_argument("--limit", type=int, default=None,
                        help="限制入库商品数量（用于测试，如 --limit 100 只入库前 100 件）")
    args = parser.parse_args()

    # 初始化 Qdrant
    qdrant_wrapper = QdrantClientWrapper(
        host=settings.qdrant_host,
        port=settings.qdrant_port,
        api_key=settings.qdrant_api_key,
        prefix=settings.qdrant_prefix,
        proxy_url=settings.proxy_url,
    )
    qdrant_wrapper.ensure_collections()
    indexer = QdrantIndexer(qdrant_wrapper)

    # 初始化向量编码客户端
    embed_client = EmbedClient(
        api_url=settings.embed_api_url,
        api_key=settings.embed_api_key,
        proxy_url=settings.proxy_url,
    )

    if not settings.embed_api_url:
        logger.warning("⚠️  embed_api_url 未配置，向量编码会失败，所有商品将被跳过")
        logger.warning("   请在 .env 中配置 EMBED_API_URL，或加 --dry-run 仅核对过滤结果")

    logger.info("==== Qdrant 商品入库开始 ====")
    logger.info("数据源: %s, dryRun=%s, shopId=%s, includeOutOfStock=%s",
                args.source, args.dry_run, args.shop_id, args.include_out_of_stock)
    logger.info("穿搭类目清单(中文): %s", OUTFIT_CATEGORIES_CN_LIST)
    logger.info("Qdrant collection: %s", COLLECTION_ITEM_STYLE)

    try:
        if args.item_id:
            # ===== 单条模式 =====
            if args.source == "mysql":
                item = fetch_single_item_from_mysql(args.item_id)
            else:
                item = await fetch_single_item_from_java(args.item_service_url, args.item_id)

            if item is None:
                logger.error("商品 %s 不存在", args.item_id)
                return

            # 单条模式做一次类目校验，非穿搭类目给出明确提示
            if item.get("category") not in CN_TO_EN:
                logger.warning("商品 %s 非穿搭类目 (category=%s)，跳过入库",
                                args.item_id, item.get("category"))
                return

            success = await index_item(indexer, embed_client, item, dry_run=args.dry_run)
            logger.info("单条入库完成: itemId=%s, success=%s", args.item_id, success)

        else:
            # ===== 全量模式 =====
            if args.source == "mysql":
                items = fetch_items_from_mysql(
                    shop_id=args.shop_id,
                    include_out_of_stock=args.include_out_of_stock,
                    min_id=args.min_id,
                    max_id=args.max_id,
                )
            else:
                items = await fetch_items_from_java(args.item_service_url, args.shop_id)

            logger.info("共拉取 %d 件穿搭类目商品，开始向量编码入库...", len(items))

            if not items:
                logger.warning("⚠️  未拉取到任何穿搭类目商品，请检查：")
                logger.warning("   1. MySQL item 表中是否有 category IN ('上衣','下装','鞋','帽子','包','配饰') 的数据")
                logger.warning("   2. status 是否 = 1（上架）")
                logger.warning("   3. stock 是否 > 0（或加 --include-out-of-stock）")
                return

            # 应用 --limit 限制（用于测试）
            if args.limit is not None and args.limit > 0:
                items = items[:args.limit]
                logger.info("⚠️  --limit=%d 生效，仅入库前 %d 件商品（测试模式）", args.limit, len(items))

            success_count = 0
            fail_count = 0
            for i, item in enumerate(items):
                try:
                    success = await index_item(indexer, embed_client, item, dry_run=args.dry_run)
                    if success:
                        success_count += 1
                    else:
                        fail_count += 1
                except Exception as e:
                    logger.error("商品 %s 入库异常: %s", item.get("id"), e, exc_info=True)
                    fail_count += 1

                if (i + 1) % 50 == 0:
                    logger.info("进度: %d/%d (成功 %d, 失败 %d)",
                                 i + 1, len(items), success_count, fail_count)

            logger.info("==== 入库完成 ====")
            logger.info("总计 %d 件, 成功 %d 件, 失败 %d 件",
                         len(items), success_count, fail_count)
            if fail_count > 0:
                logger.warning("⚠️  有 %d 件失败，常见原因：图片下载失败/向量编码失败/image 为空", fail_count)
    finally:
        await embed_client.close()


if __name__ == "__main__":
    asyncio.run(main())

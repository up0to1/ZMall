"""
下载 Unsplash 商品图片到本地（模仿商家上传图片动作）

将 60 个商品（ID 200001-200060）的 Unsplash 外链图片下载到
zmall-nginx/html/uploads/items/ 目录，并更新 MySQL item 表的 image
字段为本地路径（/uploads/items/{uuid}.jpg）。

同时同步更新 db/hm-item.sql 文件中的 image 字段，保证重新导入 SQL
时数据库也是本地路径。

模仿商家上传图片的动作：
- Java LocalFileStorage.upload(file, "items") 会：
  - 生成 UUID 文件名（去掉连字符）
  - 保存到 {basePath}/items/ 目录（basePath 默认 ../zmall-nginx/html/uploads）
  - 返回 /uploads/items/{uuid}.jpg 路径
- 本脚本复用相同逻辑，数据源从 MultipartFile 改为 HTTP 下载 Unsplash

幂等性：
- 查询条件 WHERE image LIKE '%images.unsplash.com%'，已更新为本地的自动跳过
- 可安全重复运行

用法：
    cd ai-outfit
    set PYTHONPATH=h:\Desktop\WorkPlace\Project\Cross_Big_Project\ZMall\zmall-ai
    python -m scripts.download_unsplash_images          # 下载并更新数据库 + SQL文件
    python -m scripts.download_unsplash_images --dry-run # 仅打印不下载不更新
    python -m scripts.download_unsplash_images --skip-sql-file  # 跳过更新 SQL 文件

环境变量（从 ai-outfit/.env 读取）：
    MYSQL_HOST/PORT/USERNAME/PASSWORD/DATABASE
"""
import argparse
import asyncio
import logging
import os
import sys
import uuid
from pathlib import Path

# 将项目根目录（zmall-ai）加入 sys.path，使 shared/app 包可被导入
# 文件路径：zmall-ai/ai-outfit/scripts/download_unsplash_images.py → 3 次 dirname 到 zmall-ai
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import httpx  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from app.core.config import settings  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("download_unsplash")

# ============================================================================
# 路径计算
# ============================================================================

# ZMall 项目根目录（脚本路径 parents[3]）
#   scripts/download_unsplash_images.py
#   parents[0] = scripts
#   parents[1] = ai-outfit
#   parents[2] = zmall-ai
#   parents[3] = ZMall
PROJECT_ROOT = Path(__file__).resolve().parents[3]

# 本地存储目录（模仿 LocalFileStorage 的 basePath + directory="items"）
# LocalFileStorage: basePath = "../zmall-nginx/html/uploads", directory = "items"
# 绝对路径：ZMall/zmall-nginx/html/uploads/items/
UPLOADS_DIR = PROJECT_ROOT / "zmall-nginx" / "html" / "uploads" / "items"

# URL 前缀（模仿 LocalFileStorage 的 urlPrefix + directory）
# urlPrefix = "/uploads/", directory = "items" → "/uploads/items/"
URL_PREFIX = "/uploads/items/"

# SQL 文件路径
SQL_FILE = PROJECT_ROOT / "db" / "hm-item.sql"

# 已验证可用的 Unsplash 图片池（CC0 协议可商用）
# 当原始 URL 404（LLM 编造的 photo ID 不存在）时，按类目从池中轮询选一张替代图
FALLBACK_IMAGES_BY_CATEGORY: dict[str, list[str]] = {
    "上衣": [
        "https://images.unsplash.com/photo-1521572163474-6864f9cf17ab?w=800",
        "https://images.unsplash.com/photo-1576566588028-4147f3842f27?w=800",
        "https://images.unsplash.com/photo-1583743814966-8936f5b7be1a?w=800",
    ],
    "下装": [
        "https://images.unsplash.com/photo-1542272604-787c3835535d?w=800",
        "https://images.unsplash.com/photo-1473966968600-fa801b869a1a?w=800",
        "https://images.unsplash.com/photo-1604176354204-9268737828e4?w=800",
    ],
    "鞋": [
        "https://images.unsplash.com/photo-1542291026-7eec264c27ff?w=800",
        "https://images.unsplash.com/photo-1460353581641-37baddab0fa2?w=800",
        "https://images.unsplash.com/photo-1595950653106-6c9ebd614d3a?w=800",
    ],
    "帽子": [
        "https://images.unsplash.com/photo-1576871337622-98d48d1cf531?w=800",
        "https://images.unsplash.com/photo-1521369909029-2afed882baee?w=800",
        "https://images.unsplash.com/photo-1556306535-0f09a537f0a3?w=800",
    ],
    "包": [
        "https://images.unsplash.com/photo-1548036328-c9fa89d128fa?w=800",
        "https://images.unsplash.com/photo-1553062407-98eeb64c6a62?w=800",
        "https://images.unsplash.com/photo-1581609200177-87f6cfe4e6c0?w=800",
    ],
    "配饰": [
        "https://images.unsplash.com/photo-1624222247344-550fb60583dc?w=800",
        "https://images.unsplash.com/photo-1601923000-2b6676d94803?w=800",
        "https://images.unsplash.com/photo-1591348278863-a8fb3887e2aa?w=800",
    ],
}


async def download_image(client: httpx.AsyncClient, url: str, save_path: Path) -> bool:
    """下载单张图片到本地"""
    try:
        resp = await client.get(url, follow_redirects=True, timeout=30.0)
        if resp.status_code != 200:
            logger.warning("下载失败 HTTP %s: %s", resp.status_code, url[:80])
            return False
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_bytes(resp.content)
        logger.info("下载成功: itemId=待绑定, file=%s (%d bytes)", save_path.name, len(resp.content))
        return True
    except Exception as e:
        logger.error("下载异常: %s, error=%s", url[:80], e)
        return False


def update_sql_file(url_mappings: list[tuple[int, str, str]]) -> int:
    """同步更新 db/hm-item.sql 中的 image 字段

    Args:
        url_mappings: [(item_id, old_url, new_url), ...]
    Returns:
        替换的行数
    """
    if not SQL_FILE.exists():
        logger.warning("SQL 文件不存在，跳过: %s", SQL_FILE)
        return 0

    logger.info("开始更新 SQL 文件: %s", SQL_FILE)
    content = SQL_FILE.read_text(encoding="utf-8")
    replaced = 0

    for item_id, old_url, new_url in url_mappings:
        if old_url in content:
            content = content.replace(old_url, new_url)
            replaced += 1
            logger.info("SQL 文件替换: itemId=%s", item_id)
        else:
            # 可能已经被替换过（幂等场景）
            logger.debug("SQL 文件中未找到旧 URL（可能已替换）: itemId=%s", item_id)

    if replaced > 0:
        SQL_FILE.write_text(content, encoding="utf-8")
        logger.info("SQL 文件更新完成: 替换 %d 条", replaced)
    else:
        logger.info("SQL 文件无需更新（所有 URL 已是本地路径）")

    return replaced


async def main():
    parser = argparse.ArgumentParser(description="下载 Unsplash 商品图片到本地并更新数据库")
    parser.add_argument("--dry-run", action="store_true",
                        help="仅打印不下载不更新")
    parser.add_argument("--skip-sql-file", action="store_true",
                        help="跳过更新 db/hm-item.sql 文件")
    args = parser.parse_args()

    # 连接 MySQL
    db_url = (
        f"mysql+pymysql://{settings.mysql_username}:{settings.mysql_password}"
        f"@{settings.mysql_host}:{settings.mysql_port}/{settings.mysql_database}?charset=utf8mb4"
    )
    engine = create_engine(db_url, pool_pre_ping=True)

    # 查询还是 Unsplash 外链的商品（幂等：已更新为本地的自动跳过）
    with engine.connect() as conn:
        result = conn.execute(text(
            "SELECT id, image, category FROM item "
            "WHERE image LIKE '%images.unsplash.com%' "
            "ORDER BY id"
        ))
        items = [(row[0], row[1], row[2]) for row in result]  # (id, image, category)

    logger.info("==== Unsplash 图片下载开始 ====")
    logger.info("查询到 %d 个 Unsplash 外链商品", len(items))

    if not items:
        logger.info("没有需要下载的 Unsplash 外链商品（可能已全部更新为本地路径），退出")
        engine.dispose()
        return

    if args.dry_run:
        for item_id, image_url, category in items:
            logger.info("[DRY-RUN] itemId=%s, category=%s, url=%s", item_id, category, image_url[:80])
        logger.info("[DRY-RUN] 共 %d 个商品待下载", len(items))
        engine.dispose()
        return

    # 确保目录存在
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("本地存储目录: %s", UPLOADS_DIR)

    # 构造代理 URL（images.unsplash.com 在国内无法直连，必须走代理）
    # 优先级：环境变量 HTTPS_PROXY > settings.proxy_url
    proxy_url = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY") or settings.proxy_url
    # settings.proxy_url 形如 http://127.0.0.1:7897，httpx 需要完整 URL
    client_kwargs: dict = {
        "headers": {"User-Agent": "Mozilla/5.0 ZMall/1.0 (image downloader)"},
        "timeout": 30.0,
        "follow_redirects": True,
    }
    if proxy_url:
        logger.info("使用代理下载图片: %s", proxy_url)
        client_kwargs["proxy"] = proxy_url
    else:
        logger.warning("未配置代理，images.unsplash.com 可能无法直连，下载大概率会失败")

    # 下载图片
    success_count = 0
    fail_count = 0
    fallback_count = 0
    url_mappings: list[tuple[int, str, str]] = []  # (item_id, old_url, new_url)
    # fallback 轮询计数器（按类目轮询，确保同类目多个商品不会都用同一张图）
    fallback_counter: dict[str, int] = {}

    async with httpx.AsyncClient(**client_kwargs) as client:
        for item_id, image_url, category in items:
            # 生成 UUID 文件名（模仿 LocalFileStorage 的命名规则）
            new_filename = uuid.uuid4().hex + ".jpg"
            save_path = UPLOADS_DIR / new_filename
            new_url = URL_PREFIX + new_filename

            # 下载图片
            ok = await download_image(client, image_url, save_path)

            # 原始 URL 下载失败（如 404，LLM 编造的 photo ID 不存在）→ 按 category 用 fallback 池
            if not ok:
                fallback_urls = FALLBACK_IMAGES_BY_CATEGORY.get(category, [])
                if fallback_urls:
                    idx = fallback_counter.get(category, 0)
                    fallback_url = fallback_urls[idx % len(fallback_urls)]
                    fallback_counter[category] = idx + 1
                    logger.info("itemId=%d 原始 URL 404，使用 fallback: %s",
                                item_id, fallback_url[:80])
                    # 删除可能残留的空文件
                    if save_path.exists():
                        save_path.unlink()
                    ok = await download_image(client, fallback_url, save_path)
                    if ok:
                        fallback_count += 1

            if ok:
                url_mappings.append((item_id, image_url, new_url))
                success_count += 1
                logger.info("itemId=%s 绑定: %s", item_id, new_url)
            else:
                fail_count += 1
                # 下载失败时删除空文件（如果有）
                if save_path.exists():
                    save_path.unlink()

    logger.info("图片下载完成: 成功 %d (含 fallback %d), 失败 %d",
                success_count, fallback_count, fail_count)

    # 批量更新 MySQL
    if url_mappings:
        logger.info("开始更新 MySQL item 表...")
        with engine.begin() as conn:
            for item_id, _, new_url in url_mappings:
                conn.execute(
                    text("UPDATE item SET image = :url WHERE id = :id"),
                    {"url": new_url, "id": item_id},
                )
        logger.info("MySQL 更新完成: %d 条", len(url_mappings))

    # 同步更新 SQL 文件
    if url_mappings and not args.skip_sql_file:
        update_sql_file(url_mappings)
    elif args.skip_sql_file:
        logger.info("已跳过 SQL 文件更新（--skip-sql-file）")

    engine.dispose()

    logger.info("==== 完成 ====")
    logger.info("总计 %d, 成功 %d (含 fallback %d), 失败 %d",
                len(items), success_count, fallback_count, fail_count)
    if fail_count > 0:
        logger.warning("⚠️  有 %d 个商品下载失败，可重新运行本脚本重试（已成功的会自动跳过）", fail_count)


if __name__ == "__main__":
    asyncio.run(main())

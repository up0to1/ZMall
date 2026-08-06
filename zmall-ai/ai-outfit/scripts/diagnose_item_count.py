"""
诊断脚本：统计 MySQL item 表中各类商品的分布，定位 220 vs 201 差异原因。

用法（任意 Python 环境，仅需 pymysql）：
    cd ai-outfit
    python -m scripts.diagnose_item_count

依赖：pymysql（ai-outfit 已依赖 pymysql）

输出：
    - item 表总条数
    - 各 status 值的条数（1=上架, 2=下架, 3=删除）
    - 各 category 值的条数（穿搭类目 vs 非穿搭类目）
    - 各 stock 分布（>0 / =0 / <0）
    - 应用 index_items.py 3 个过滤条件后的条数
    - 被过滤掉的穿搭类目商品明细
"""
import sys
from pathlib import Path

# 直接定义穿搭类目清单（避免依赖 shared.qdrant_client 触发 pydantic_settings 导入失败）
OUTFIT_CATEGORIES_CN_LIST = ["上衣", "下装", "全身套装", "鞋", "帽子", "包", "配饰"]


def load_db_config_from_env() -> dict:
    """从 ai-outfit/.env 读取 MySQL 配置（不依赖 pydantic_settings）"""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    config = {
        "host": "192.168.59.128",
        "port": 3306,
        "user": "root",
        "password": "123456",
        "database": "hm-item",
    }
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if key == "MYSQL_HOST":
                config["host"] = value
            elif key == "MYSQL_PORT":
                config["port"] = int(value)
            elif key == "MYSQL_USERNAME":
                config["user"] = value
            elif key == "MYSQL_PASSWORD":
                config["password"] = value
            elif key == "MYSQL_DATABASE":
                config["database"] = value
    return config


def main():
    # 尝试导入 pymysql，失败时给出明确提示
    try:
        import pymysql
    except ImportError:
        print("ERROR: pymysql 未安装，请用 ai-outfit 对应的 conda 环境运行此脚本")
        print("       激活环境后重试：python -m scripts.diagnose_item_count")
        sys.exit(1)

    cfg = load_db_config_from_env()
    print(f"\n{'=' * 60}")
    print(f"MySQL 数据库: {cfg['database']} @ {cfg['host']}:{cfg['port']}")
    print(f"穿搭类目清单(中文): {OUTFIT_CATEGORIES_CN_LIST}")
    print(f"{'=' * 60}\n")

    conn = pymysql.connect(
        host=cfg["host"],
        port=cfg["port"],
        user=cfg["user"],
        password=cfg["password"],
        database=cfg["database"],
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )

    try:
        with conn.cursor() as cur:
            # 1. item 表总条数
            cur.execute("SELECT COUNT(*) AS cnt FROM item")
            total = cur.fetchone()["cnt"]
            print(f"[1] item 表总条数: {total}\n")

            # 2. 按 status 分布
            print("[2] status 分布:")
            cur.execute("SELECT status, COUNT(*) AS cnt FROM item GROUP BY status ORDER BY status")
            status_map = {1: "上架", 2: "下架", 3: "删除"}
            for row in cur.fetchall():
                label = status_map.get(row["status"], f"未知({row['status']})")
                print(f"    status={row['status']} ({label}): {row['cnt']} 条")
            print()

            # 3. 按 category 分布
            print("[3] category 分布:")
            cur.execute(
                "SELECT category, COUNT(*) AS cnt FROM item GROUP BY category ORDER BY cnt DESC"
            )
            outfit_total = 0
            non_outfit_total = 0
            for row in cur.fetchall():
                category = row["category"] or "(NULL)"
                cnt = row["cnt"]
                is_outfit = category in OUTFIT_CATEGORIES_CN_LIST
                tag = "[穿搭]" if is_outfit else "[非穿搭]"
                print(f"    {tag} {category}: {cnt} 条")
                if is_outfit:
                    outfit_total += cnt
                else:
                    non_outfit_total += cnt
            print(f"    -> 穿搭类目小计: {outfit_total} 条")
            print(f"    -> 非穿搭类目小计: {non_outfit_total} 条\n")

            # 4. 按 stock 分布
            print("[4] stock 分布:")
            cur.execute(
                "SELECT CASE WHEN stock > 0 THEN 'stock>0' WHEN stock = 0 THEN 'stock=0' "
                "ELSE 'stock<0' END AS bucket, COUNT(*) AS cnt "
                "FROM item GROUP BY bucket ORDER BY bucket"
            )
            for row in cur.fetchall():
                print(f"    {row['bucket']}: {row['cnt']} 条")
            print()

            # 5. 应用 index_items.py 的 3 个过滤条件
            placeholders = ",".join(["%s"] * len(OUTFIT_CATEGORIES_CN_LIST))
            params = tuple(OUTFIT_CATEGORIES_CN_LIST)

            cur.execute(
                f"SELECT COUNT(*) AS cnt FROM item WHERE category IN ({placeholders})",
                params,
            )
            c1 = cur.fetchone()["cnt"]

            cur.execute(
                f"SELECT COUNT(*) AS cnt FROM item WHERE category IN ({placeholders}) AND status = 1",
                params,
            )
            c2 = cur.fetchone()["cnt"]

            cur.execute(
                f"SELECT COUNT(*) AS cnt FROM item WHERE category IN ({placeholders}) "
                f"AND status = 1 AND stock > 0",
                params,
            )
            c3 = cur.fetchone()["cnt"]

            print(f"[5] 应用 index_items.py 过滤条件后的条数:")
            print(f"    条件1: category IN (穿搭类目)                                 -> {c1} 条")
            print(f"    条件2: 条件1 + status = 1 (上架)                             -> {c2} 条")
            print(f"    条件3: 条件2 + stock > 0 (默认，不含 --include-out-of-stock)  -> {c3} 条")
            print(f"    条件4: 条件2 (含 --include-out-of-stock)                     -> {c2} 条 (= 条件2)")
            print()

            # 6. 列出被过滤掉的穿搭类目商品（status != 1 或 stock <= 0）
            print("[6] 被过滤掉的穿搭类目商品明细（前 30 条）:")
            cur.execute(
                f"SELECT id, name, category, status, stock FROM item "
                f"WHERE category IN ({placeholders}) AND (status != 1 OR stock <= 0) "
                f"ORDER BY id LIMIT 30",
                params,
            )
            rows = cur.fetchall()
            if not rows:
                print("    (无)")
            else:
                print(f"    {'id':<8} {'status':<8} {'stock':<8} {'category':<12} name")
                for row in rows:
                    name = (row["name"] or "")[:30]
                    print(f"    {row['id']:<8} {row['status']:<8} {row['stock']:<8} {row['category']:<12} {name}")
            print()

            print(f"{'=' * 60}")
            print(f"差异分析 (总 {total} 条):")
            print(f"  - 非穿搭类目过滤掉: {total - c1} 条")
            print(f"  - status != 1 过滤掉: {c1 - c2} 条 (穿搭类目中下架/删除的)")
            print(f"  - stock <= 0 过滤掉: {c2 - c3} 条 (穿搭类目且上架，但缺货的)")
            print(f"  - 你运行 --include-out-of-stock 后剩 {c2} 条 (与 201 差异: {c2 - 201})")
            print(f"{'=' * 60}\n")
    finally:
        conn.close()


if __name__ == "__main__":
    main()

"""
列出数据库中 category='全身裙' 或 '半身裙' 的所有商品 ID 和当前 category,
用于核对 SQL 文件里这些商品的 category 字段。
"""
import sys
from pathlib import Path

OUTFIT_CATEGORIES_CN_LIST = ["全身裙", "半身裙"]


def load_db_config_from_env() -> dict:
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
    try:
        import pymysql
    except ImportError:
        print("ERROR: pymysql 未安装")
        sys.exit(1)

    cfg = load_db_config_from_env()
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
            placeholders = ",".join(["%s"] * len(OUTFIT_CATEGORIES_CN_LIST))
            cur.execute(
                f"SELECT id, name, category FROM item "
                f"WHERE category IN ({placeholders}) ORDER BY id",
                tuple(OUTFIT_CATEGORIES_CN_LIST),
            )
            rows = cur.fetchall()
            print(f"\n数据库中 category='全身裙' 或 '半身裙' 的商品共 {len(rows)} 条:\n")
            print(f"  {'id':<6} {'category':<10} name")
            for row in rows:
                name = (row["name"] or "")[:40]
                print(f"  {row['id']:<6} {row['category']:<10} {name}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()

"""
清理 Qdrant collection（删除后由 index_items.py 自动重建）。

用法：
    cd ai-outfit
    python -m scripts.clean_qdrant_collection            # 删除 item_style collection
    python -m scripts.clean_qdrant_collection --dry-run  # 仅查看当前 collection 状态

清理后再运行：
    python -m scripts.index_items   # 重建 collection 并全量入库
"""
import argparse
import json
import os
import ssl
import sys
import urllib.request
import urllib.error
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def load_env() -> dict:
    """从 ai-outfit/.env 读取 Qdrant 配置"""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    cfg = {
        "host": "",
        "port": 6333,
        "api_key": "",
        "prefix": "",
        "proxy_url": "",
    }
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if key == "QDRANT_HOST":
                cfg["host"] = value
            elif key == "QDRANT_PORT":
                cfg["port"] = int(value)
            elif key == "QDRANT_API_KEY":
                cfg["api_key"] = value
            elif key == "QDRANT_PREFIX":
                cfg["prefix"] = value
            elif key == "PROXY_URL":
                cfg["proxy_url"] = value
    return cfg


def http_request(url: str, method: str = "GET", headers: dict = None, proxy_url: str = None) -> tuple:
    """简单 HTTP 请求封装，返回 (status_code, body_text)"""
    headers = headers or {}
    req = urllib.request.Request(url, method=method, headers=headers)

    # 代理设置
    proxy_handlers = []
    if proxy_url:
        proxy_handlers.append(urllib.request.ProxyHandler({
            "http": proxy_url,
            "https": proxy_url,
        }))

    # HTTPS 需要未验证的 SSL context（Qdrant Cloud 用自签证书或代理时会用到）
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    https_handler = urllib.request.HTTPSHandler(context=ctx)

    if proxy_handlers:
        opener = urllib.request.build_opener(*proxy_handlers, https_handler)
    else:
        opener = urllib.request.build_opener(https_handler)

    try:
        with opener.open(req, timeout=30) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")


def main():
    parser = argparse.ArgumentParser(description="清理 Qdrant collection")
    parser.add_argument("--dry-run", action="store_true", help="仅查看 collection 状态，不删除")
    parser.add_argument("--collection", default="item_style", help="collection 名称（默认 item_style）")
    args = parser.parse_args()

    cfg = load_env()
    if not cfg["host"]:
        print("ERROR: QDRANT_HOST 未配置")
        sys.exit(1)

    # 构造 base url
    host = cfg["host"]
    if host.startswith("https://"):
        scheme = "https"
        hostname = host[len("https://"):]
    elif host.startswith("http://"):
        scheme = "http"
        hostname = host[len("http://"):]
    else:
        scheme = "http"
        hostname = host
    base_url = f"{scheme}://{hostname}:{cfg['port']}{cfg['prefix']}"
    headers = {}
    if cfg["api_key"]:
        headers["api-key"] = cfg["api_key"]

    proxy_url = cfg["proxy_url"] if cfg["proxy_url"] else None

    print(f"Qdrant 地址: {base_url}")
    print(f"Collection: {args.collection}")
    print(f"代理: {proxy_url if proxy_url else '(无)'}")
    print()

    # 1. 查询所有 collections
    status, body = http_request(f"{base_url}/collections", headers=headers, proxy_url=proxy_url)
    if status != 200:
        print(f"ERROR: 查询 collections 失败, status={status}, body={body}")
        sys.exit(1)
    data = json.loads(body)
    collections = [c["name"] for c in data.get("result", {}).get("collections", [])]
    print(f"当前 Qdrant 中所有 collections: {collections}")

    if args.collection not in collections:
        print(f"\nCollection '{args.collection}' 不存在，无需清理")
        return

    # 2. 查询目标 collection 详情
    status, body = http_request(
        f"{base_url}/collections/{args.collection}", headers=headers, proxy_url=proxy_url
    )
    if status != 200:
        print(f"ERROR: 查询 collection 详情失败, status={status}, body={body}")
        sys.exit(1)
    detail = json.loads(body).get("result", {})
    points_count = detail.get("points_count", 0)
    vectors_count = detail.get("vectors_count", 0)
    print(f"Collection '{args.collection}' 详情:")
    print(f"  points_count: {points_count}")
    print(f"  vectors_count: {vectors_count}")

    if args.dry_run:
        print(f"\n[DRY-RUN] 未删除 collection '{args.collection}'")
        return

    # 3. 删除 collection
    print(f"\n正在删除 collection '{args.collection}'...")
    status, body = http_request(
        f"{base_url}/collections/{args.collection}",
        method="DELETE",
        headers=headers,
        proxy_url=proxy_url,
    )
    if status != 200:
        print(f"ERROR: 删除 collection 失败, status={status}, body={body}")
        sys.exit(1)
    print(f"[OK] Collection '{args.collection}' 已删除")
    print(f"\n下一步：运行 `python -m scripts.index_items` 重建 collection 并全量入库")


if __name__ == "__main__":
    main()

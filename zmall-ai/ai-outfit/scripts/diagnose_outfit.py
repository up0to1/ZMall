"""诊断 AI 随心搭两个问题：
1. 系统模特列表是否正常返回
2. Redis 残留锁/任务状态
"""
import asyncio
import logging
import sys
import os

# 添加项目根路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import redis.asyncio as aioredis
import httpx

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


async def main():
    # 1. 检查 Redis 残留锁和任务状态
    r = aioredis.Redis(host="192.168.59.128", port=6379, db=0, decode_responses=True)
    print("=" * 60)
    print("1. 检查 Redis 残留锁和任务状态")
    print("=" * 60)

    lock_keys = await r.keys("lock:outfit:*")
    print(f"  lock:outfit:* keys: {lock_keys}")

    task_keys = await r.keys("ai:task:status:*")
    print(f"  ai:task:status:* keys: {task_keys}")
    for k in task_keys:
        val = await r.get(k)
        ttl = await r.ttl(k)
        print(f"    {k}: TTL={ttl}s, value={val[:200] if val else None}")

    # 2. 检查 MySQL system_model_image 表的 is_active 状态
    print()
    print("=" * 60)
    print("2. 检查 MySQL system_model_image 表")
    print("=" * 60)
    try:
        import pymysql
        conn = pymysql.connect(
            host=os.getenv("MYSQL_HOST", "192.168.59.128"), port=3306, user="root",
            password=os.getenv("MYSQL_PASSWORD", ""), database="hm-item", charset="utf8mb4"
        )
        cur = conn.cursor()
        cur.execute("SELECT id, uploader_user_id, gender, is_active, is_default, image_url FROM system_model_image ORDER BY id LIMIT 20")
        rows = cur.fetchall()
        print(f"  总共查询到 {len(rows)} 条（LIMIT 20）:")
        for row in rows:
            print(f"    id={row[0]}, uploader={row[1]}, gender={row[2]}, is_active={row[3]}, is_default={row[4]}, url={row[5][:50] if row[5] else None}")

        cur.execute("SELECT is_active, COUNT(*) FROM system_model_image GROUP BY is_active")
        print()
        print("  is_active 分布:")
        for row in cur.fetchall():
            print(f"    is_active={row[0]}: {row[1]} 条")

        conn.close()
    except Exception as e:
        print(f"  MySQL 查询失败: {e}")
        print("  （需要 pymysql: pip install pymysql）")

    # 3. 测试 Python ai-outfit 的 /v1/outfit/agent/system-models 接口
    print()
    print("=" * 60)
    print("3. 测试 Python ai-outfit 接口（需要 ai-outfit 服务运行中）")
    print("=" * 60)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            # 先测试健康检查
            try:
                resp = await client.get("http://localhost:9001/health")
                print(f"  /health: status={resp.status_code}, body={resp.text[:200]}")
            except Exception as e:
                print(f"  /health 失败: {e}")
                print("  （ai-outfit 服务可能未启动）")

            # 测试系统模特列表接口（需要 token，这里只测试连通性）
            try:
                resp = await client.get("http://localhost:9001/v1/outfit/agent/system-models")
                print(f"  /v1/outfit/agent/system-models (无token): status={resp.status_code}, body={resp.text[:200]}")
            except Exception as e:
                print(f"  /v1/outfit/agent/system-models 失败: {e}")
    except Exception as e:
        print(f"  HTTP 请求失败: {e}")

    # 4. 直接调用 Java item-service 的接口（绕过 Python）
    print()
    print("=" * 60)
    print("4. 直接调用 Java item-service 接口")
    print("=" * 60)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            # item-service 端口 8081
            resp = await client.get(
                "http://localhost:8081/items/admin/ai-model/system-images",
                headers={"user-info": "1"},  # 模拟用户ID=1
                params={"page": 1, "size": 10},
            )
            print(f"  GET /items/admin/ai-model/system-images: status={resp.status_code}")
            if resp.status_code == 200:
                data = resp.json()
                # 兼容包装格式
                if isinstance(data, dict) and data.get("data") is not None:
                    data = data["data"]
                if isinstance(data, dict):
                    print(f"  total={data.get('total')}, pages={data.get('pages')}")
                    lst = data.get("list") or []
                    print(f"  list 长度={len(lst)}")
                    for item in lst[:5]:
                        print(f"    id={item.get('id')}, isActive={item.get('isActive')}, "
                              f"gender={item.get('gender')}, url={str(item.get('imageUrl',''))[:50]}")
            else:
                print(f"  body={resp.text[:300]}")
    except Exception as e:
        print(f"  调用 Java item-service 失败: {e}")

    await r.close()
    print()
    print("=" * 60)
    print("诊断完成")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())

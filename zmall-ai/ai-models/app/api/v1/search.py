"""
向量检索接口（调试/测试用）

供前端或调试时查询商品的相似搭配推荐。
纯文本向量模式：拼接商品文本属性后用 text-embedding-v4 编码。
"""
import asyncio
import json
import logging
from fastapi import APIRouter, Query
from pydantic import BaseModel
from typing import Optional

from app.api.deps import get_qdrant_searcher, get_embed_client, get_java_client
from shared.qdrant_client.searcher import QdrantSearcher
from shared.model_client.embed_client import EmbedClient
from shared.java_client import JavaClient

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/search", tags=["向量检索"])


class SearchResultItem(BaseModel):
    item_id: int
    score: float
    shop_id: Optional[int] = None
    category: Optional[str] = None
    price: Optional[float] = None


class SearchResponse(BaseModel):
    query_item_id: Optional[int] = None
    total: int
    items: list[SearchResultItem]


def _build_search_item_text(item: dict) -> str:
    """拼接商品文本用于向量编码（纯文本向量模式）

    与 index_items.py 的 build_item_text 逻辑一致：
    拼接 name + category + color + season + styleTags
    """
    parts = []
    name = item.get("name")
    if name:
        parts.append(str(name).strip())
    category = item.get("category")
    if category:
        parts.append(str(category).strip())
    color = item.get("color")
    if color:
        parts.append(str(color).strip())
    season = item.get("season")
    if season:
        parts.append(str(season).strip())
    raw_style = item.get("styleTags") or item.get("style_tags")
    if raw_style:
        try:
            if isinstance(raw_style, str):
                parsed = json.loads(raw_style)
                if isinstance(parsed, list):
                    parts.extend(str(s) for s in parsed if s)
            elif isinstance(raw_style, list):
                parts.extend(str(s) for s in raw_style if s)
        except (ValueError, TypeError):
            pass
    return " ".join(parts) if parts else ""


@router.get("/similar", response_model=SearchResponse, summary="基于商品ID查找相似搭配")
async def find_similar(
    item_id: int = Query(..., description="基准商品ID"),
    shop_id: int | None = Query(None, description="限定同店（不填则全平台）"),
    limit: int = Query(5, description="返回数量", ge=1, le=20),
):
    """根据商品ID查找相似搭配商品

    纯文本向量模式：从 item-service 获取商品文本属性 → 拼接文本 → encode_text → Qdrant 检索
    """
    # 1. 从 item-service 获取商品详情（通过 Nacos 服务发现，复用 JavaClient 单例）
    java_client: JavaClient = await get_java_client()
    items = await java_client.get_items_by_ids([item_id])
    if not items:
        return SearchResponse(query_item_id=item_id, total=0, items=[])
    item = items[0]

    # 2. 拼接商品文本并编码向量（纯文本向量模式）
    item_text = _build_search_item_text(item)
    if not item_text:
        return SearchResponse(query_item_id=item_id, total=0, items=[])

    embed_client: EmbedClient = await get_embed_client()
    vector = await embed_client.encode_text(item_text)
    if vector is None:
        return SearchResponse(query_item_id=item_id, total=0, items=[])

    # 3. Qdrant 检索（同步调用，放到线程池避免阻塞事件循环）
    searcher: QdrantSearcher = await get_qdrant_searcher()
    results = await asyncio.to_thread(
        searcher.search_complementary_items,
        query_vector=vector,
        shop_ids=[shop_id] if shop_id is not None else None,
        limit=limit,
    )

    return SearchResponse(
        query_item_id=item_id,
        total=len(results),
        items=[SearchResultItem(**r) for r in results],
    )

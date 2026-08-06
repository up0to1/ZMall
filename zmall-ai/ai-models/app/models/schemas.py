"""
Pydantic 请求/响应模型

此处仅保留 AI 模特图结果轮询、Ozon、搜索相关的 schema。
注：AI 模特图生成由 Java item-service 在 /items/admin/ai-model/* 提供，
    Python 仅提供 /api/v1/model/result/** 兜底轮询，无生成请求 schema。

多换装模式搭配组合预览接口 schema
"""
from typing import Optional
from pydantic import BaseModel, Field


# ===== AI 模特 =====
class ModelResultResponse(BaseModel):
    """AI 模特图结果响应"""
    taskId: str
    status: str
    resultUrls: Optional[list[str]] = None
    errorMsg: Optional[str] = None


# ===== v5 多换装模式：搭配组合预览 =====
class OutfitCombinationItem(BaseModel):
    """搭配组合预览请求中的商品项（精简版，仅含推荐所需字段）"""
    itemId: int
    category: str = Field("", description="品类：上衣/下装/全身套装/帽子")
    name: str = Field("", description="商品名称")
    color: str = Field("", description="主色")
    styleTags: list[str] = Field(default_factory=list, description="风格标签")


class OutfitCombinationRequest(BaseModel):
    """搭配组合预览请求体"""
    items: list[OutfitCombinationItem] = Field(..., description="商家选定的商品列表")


class OutfitCombinationResponse(BaseModel):
    """搭配组合预览响应体"""
    combinations: list[list[int]] = Field(
        default_factory=list,
        description="1-4 套商品 ID 组合",
    )
    reasons: list[str] = Field(
        default_factory=list,
        description="每套组合的推荐理由（与 combinations 等长）",
    )
    source: str = Field(
        "llm",
        description="推荐来源：llm（LLM 智能推荐）/ fallback（规则降级）",
    )


# ===== 通用 =====
class HealthResponse(BaseModel):
    """健康检查响应"""
    status: str = "UP"
    service: str = "ai-models"

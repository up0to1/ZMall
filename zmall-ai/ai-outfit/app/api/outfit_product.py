"""
AI 随心搭·商品驱动模式 API（U1 统一架构：从 ai-models 迁移到 ai-outfit）

请求流：
  ① 用户在商品详情页点"AI 搭配" → POST /api/v1/outfit/generate
  ② Gateway JWT 鉴权 → 透传 user-info（userId）
  ③ AgentService.generate_outfit 同步：配额预扣 → 写任务状态 → 启动异步 LangGraph 工作流
  ④ HTTP 返回 { taskId, status: "PROCESSING" }

异步流（不阻塞 HTTP）：
  ⑤ LangGraph 6 节点推理（mode="product" 分支，30s 超时）
  ⑥ Redis 更新 SUCCESS/FAILED + WebSocket 推送（type=OUTFIT_PRODUCT）+ MQ 通知 Java 配额确认/回滚

兜底：
  ⑦ 前端未收到 WS → 用 taskId 轮询 GET /api/v1/outfit/result/{taskId}

照片会话（两种模式共用）：
  - POST /api/v1/outfit/photo 上传真人照片（存 Redis，TTL 30min）
  - DELETE /api/v1/outfit/photo 清除照片
  - Redis Key ai:photo:session:{userId} 与原 ai-models 一致

路由前缀 /api/v1/outfit（无 /agent 后缀，与原 ai-models 保持一致，前端无需改路由）
"""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.deps import get_oss_uploader, get_redis
from app.schemas.common import TaskResponse, validate_task_id
from app.services.agent_service import get_agent_service
from app.services.photo_session import PhotoSessionService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/outfit", tags=["AI随心搭-商品驱动"])


# ============================================================
# 请求/响应模型
# ============================================================
class PhotoUploadRequest(BaseModel):
    """照片上传请求（两种模式共用）"""
    photo: str = Field(..., description="Base64 编码的用户真人照片")


class PhotoUploadResponse(BaseModel):
    """照片上传响应"""
    photoSessionKey: str


class OutfitGenerateRequest(BaseModel):
    """商品驱动模式换装请求

    用户在商品详情页点击"AI 搭配"按钮时触发，传入主商品 ID 列表。
    AgentService 会调 JavaClient.get_items_by_ids 拉主商品详情，
    节点1 按 main_item_ids 走商品驱动分支（encode_text + 推导互补品类）。

    性别与服装匹配：
    - 用户可同时选定系统模特作为 VTON base，AI 据模特性别过滤互补商品
    - 若用户上传自拍且未选系统模特，则按自拍分析性别过滤
    - 主商品本身不参与性别过滤（用户已选定，假设用户清楚该商品是否适合自己）
    """
    itemIds: list[int] = Field(..., min_length=1, description="主商品 ID 列表（取第一件作为换装基准）")
    photoSessionKey: Optional[str] = Field(None, description="照片会话 Key（用户上传真人照片后返回）")
    # 删除 prompt 预留字段——agent_service.generate_outfit 签名虽接收但方法体内从未引用，
    # 保留会误导前端以为传入 prompt 会生效。如后续需启用，再加回并在节点1/3 注入 LLM 上下文。
    # 性别与服装匹配
    systemModelId: Optional[int] = Field(None, description="用户选定的系统模特图 ID，节点1 据此下载模特图作 VTON base")
    systemModelImageUrl: Optional[str] = Field(None, description="系统模特图 URL（前端从模特列表选中后传入，避免 Python 再调 Java）")
    systemModelGender: Optional[str] = Field(None, pattern="^(male|female)$",
                                              description="系统模特性别 male/female，节点1 直接用作 target_gender 进行 Qdrant 性别过滤")
    userBodyProfileId: Optional[int] = Field(None, description="用户身体信息档案 ID（真人照片模式必填，系统模特体验版可不填）")

    # ===== 天气服务=====
    # 前端通过浏览器 IP 定位获取用户城市名，传给后端用于天气查询
    # 留空时后端用默认城市"北京"兜底
    userCity: Optional[str] = Field(None, max_length=50,
                                     description="用户所在城市（前端 IP 定位获取），用于天气查询，留空走默认城市")
    userCountry: Optional[str] = Field(None, max_length=50,
                                        description="用户所在国家（前端 IP 定位获取），用于时尚趋势查询，留空走默认")


# ============================================================
# 照片会话接口（两种模式共用）
# ============================================================
@router.post("/photo", response_model=PhotoUploadResponse, summary="上传用户真人照片")
async def upload_photo(req: PhotoUploadRequest, request: Request):
    """上传真人照片到 Redis 会话（TTL 30min）

    两种模式共用同一会话存储：
    - 商品驱动模式：POST /api/v1/outfit/generate 前调本接口上传照片
    - 风格驱动模式：POST /api/v1/outfit/agent/recommend 前调本接口上传照片

    限制 base64 照片大小 ≤10MB（与千问 VTON API 上限一致），
    避免大照片直接写 Redis 导致内存压力和 OOM。
    """
    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        raise HTTPException(status_code=401, detail="无法识别用户身份，请先登录")

    # 照片大小校验
    # base64 字符串字节数 ≈ 原始图片字节数 × 4/3
    # 限制 base64 ≤ 10MB（约对应原图 7.5MB），与千问 VTON API 图片上限对齐
    MAX_PHOTO_BYTES = 10 * 1024 * 1024  # 10MB
    if len(req.photo.encode("utf-8")) > MAX_PHOTO_BYTES:
        raise HTTPException(
            status_code=413,
            detail="照片过大，请压缩到 10MB 以下后重试",
        )

    redis = await get_redis()
    # v3.1：注入 OssUploader，上传照片时同步持久化到 OSS（或本地降级）
    oss_uploader = await get_oss_uploader()
    service = PhotoSessionService(redis, oss_uploader)
    session_key = await service.upload_photo(user_id, req.photo)
    return PhotoUploadResponse(photoSessionKey=session_key)


@router.delete("/photo", summary="清除会话照片")
async def clear_photo(request: Request):
    """清除会话照片"""
    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        raise HTTPException(status_code=401, detail="无法识别用户身份，请先登录")

    redis = await get_redis()
    service = PhotoSessionService(redis)
    await service.clear_photo(user_id)
    return {"msg": "照片已清除"}


# ============================================================
# 商品驱动模式换装生成
# ============================================================
@router.post("/generate", response_model=TaskResponse, summary="商品驱动模式换装生成")
async def generate_outfit(req: OutfitGenerateRequest, request: Request):
    """商品驱动模式换装生成入口

    流程（U1 统一架构）：
      ① AgentService.generate_outfit 同步：配额预扣 → 写任务状态 → 启动异步 LangGraph 工作流
      ② LangGraph 6 节点推理（mode="product"）：
         - 节点1：拉主商品 + encode_text + 推导互补品类
         - 节点2：Qdrant 同店向量检索互补商品
         - 节点3：取每品类 Top1 + 主商品（isMain=true）组成 3 套候选（LLM Top3 决策）
         - 节点3.5：Reflection 自检（替换互补商品，主商品保留）
         - 节点4：VTON 换装 + PIL 多件合成（复用 _main_item_bytes）
         - 节点5：OSS 上传 + 组装最终搭配
      ③ Redis 更新 SUCCESS/FAILED + WS 推送（type=OUTFIT_PRODUCT）+ MQ 通知 Java 配额确认/回滚

    支持多轮反馈（与风格驱动对齐）。
    """
    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        raise HTTPException(status_code=401, detail="无法识别用户身份，请先登录")

    if not req.itemIds:
        raise HTTPException(status_code=400, detail="itemIds 不能为空")

    agent_service = await get_agent_service()
    task_id, error_msg = await agent_service.generate_outfit(
        user_id=user_id,
        item_ids=req.itemIds,
        photo_session_key=req.photoSessionKey,
        system_model_id=req.systemModelId,
        system_model_image_url=req.systemModelImageUrl,
        system_model_gender=req.systemModelGender,
        user_body_profile_id=req.userBodyProfileId,
        user_city=req.userCity,
        user_country=req.userCountry,
    )

    # 配额预扣被拒绝 → 直接返回前端"次数或余额不足"
    if error_msg:
        raise HTTPException(status_code=403, detail=error_msg)

    logger.info("[商品驱动] 推荐任务: taskId=%s, userId=%s, itemIds=%s, "
                 "systemModelId=%s, systemModelGender=%s, userCity=%s, userCountry=%s",
                 task_id, user_id, req.itemIds, req.systemModelId, req.systemModelGender,
                 req.userCity, req.userCountry)
    return TaskResponse(taskId=task_id)


# ============================================================
# v3.2：商品驱动模式多轮反馈
# ============================================================
class ProductFeedbackRequest(BaseModel):
    """商品驱动模式多轮反馈请求（v3.2）

    与风格驱动 AgentFeedbackRequest 差异：
    - 不支持 wantStyleTags（商品驱动无 style_tags 概念）
    - 不支持 note ReAct（商品驱动不触发 Tool calling）
    - 主商品 isMain=True 不参与替换
    - action 限制为：accept / replace_single / replace / regenerate_all
    """
    taskId: str = Field(..., description="原生成任务 ID")
    feedback: str = Field(..., min_length=1, max_length=200,
                          description="用户反馈原文，如'不喜欢这个颜色，换下装'")
    outfitIndex: Optional[int] = Field(None, ge=0, le=2,
                                        description="点哪换哪：搭配索引（0-based）")
    itemIndex: Optional[int] = Field(None, ge=0, le=5,
                                      description="点哪换哪：单品索引（0-based）")
    dislikeColors: Optional[list[str]] = Field(None,
                                                description="不喜欢的颜色（英文），同会话累积")
    dislikeItemIds: Optional[list[int]] = Field(None,
                                                 description="本轮不喜欢的商品 ID，仅本轮生效")
    retryVtonItemIds: Optional[list[int]] = Field(None,
                                                   description="本轮 VTON 效果差的商品 ID（商品本身 OK，仅重新换装不换商品），仅本轮生效不累积")


@router.post("/feedback", response_model=TaskResponse, summary="商品驱动模式多轮反馈（每轮扣 credits）")
async def feedback_product(req: ProductFeedbackRequest, request: Request):
    """商品驱动模式多轮反馈入口（v3.2）

    流程：
      ① 读取原任务 state 快照 → ② LLM 解析反馈 → ③ 构造新一轮 initial_state
      → ④ 重新 ainvoke LangGraph 工作流（每轮扣 credits） → ⑤ WS 推送新结果

    特殊处理：
      - 主商品 isMain=True 不参与替换（用户已选定）
      - action=adjust_style 降级为 regenerate_all
      - 每轮反馈扣 credits，同会话最多 3 轮
    """
    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        raise HTTPException(status_code=401, detail="无法识别用户身份，请先登录")

    if not req.feedback.strip():
        raise HTTPException(status_code=400, detail="feedback 不能为空")

    validate_task_id(req.taskId)  # H8: UUID 格式校验
    agent_service = await get_agent_service()
    task_id, error_msg, error_code = await agent_service.feedback_product(
        task_id=req.taskId,
        user_id=user_id,
        feedback=req.feedback,
        outfit_index=req.outfitIndex,
        item_index=req.itemIndex,
        dislike_colors=req.dislikeColors,
        dislike_item_ids=req.dislikeItemIds,
        retry_vton_item_ids=req.retryVtonItemIds,
        note=None,  # 商品驱动不支持 note ReAct
    )

    if error_msg:
        status_map = {
            "NOT_FOUND": 404,
            "FINISHED": 409,
            "CONCURRENT": 429,
            "ROUND_LIMIT": 403,
        }
        status_code = status_map.get(error_code or "", 400)
        raise HTTPException(status_code=status_code, detail=error_msg)

    logger.info("[商品驱动] 多轮反馈任务: taskId=%s, userId=%s, feedback=%s, "
                 "outfitIdx=%s, itemIdx=%s, dislikeColors=%s, dislikeItems=%s, retryVtonItems=%s",
                 task_id, user_id, req.feedback[:50], req.outfitIndex, req.itemIndex,
                 req.dislikeColors, req.dislikeItemIds, req.retryVtonItemIds)
    return TaskResponse(taskId=task_id, msg="已收到反馈，正在调整")


# ============================================================
# 任务结果查询（兜底轮询，两种模式共用）
# ============================================================
@router.get("/result/{task_id}", summary="查询换装结果（兜底轮询）")
async def get_result(task_id: str, request: Request):
    """前端未收到 WS 推送时，用 taskId 轮询查询任务状态

    两种模式共用：
    - 商品驱动模式：GET /api/v1/outfit/result/{taskId}
    - 风格驱动模式：GET /api/v1/outfit/agent/result/{taskId}
    两端读取同一 Redis Key（ai:task:status:{taskId}），返回格式一致。
    """
    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        raise HTTPException(status_code=401, detail="无法识别用户身份，请先登录")
    validate_task_id(task_id)  # H8: UUID 格式校验
    agent_service = await get_agent_service()
    data = await agent_service.get_task_result(task_id, user_id)
    if data:
        return data
    return {"taskId": task_id, "status": "FAILED", "errorMsg": "任务不存在或已过期"}

"""
AI 随心搭·风格驱动模式 API

请求流：
  ① 用户选风格标签/输场景 → POST /recommend
  ② Gateway JWT 鉴权 → 透传 user-info（userId）
  ③ AgentService 同步：配额预扣 → 写任务状态 → 启动异步 LangGraph 工作流
  ④ HTTP 返回 { taskId, status: "PROCESSING" }

异步流（不阻塞 HTTP）：
  ⑤ LangGraph 5 节点推理（30s 超时）
  ⑥ Redis 更新 SUCCESS/FAILED + WebSocket 推送 + MQ 通知 Java 配额确认/回滚

兜底：
  ⑦ 前端未收到 WS → 用 taskId 轮询 GET /result/{taskId}
"""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.deps import get_java_client
from app.schemas.common import TaskResponse, validate_task_id
from app.schemas.outfit import TaskResultResponse
from app.services.agent_service import get_agent_service
from shared.outfit_common import (
    CategoryConflictError,
    validate_category_combination,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/outfit/agent", tags=["AI随心搭-风格驱动"])


class AgentRecommendRequest(BaseModel):
    """风格驱动模式请求（结构化表单 + 选填备注，衣橱）

    所有字段均可选，但 styleTags/color/sceneDesc/note 任一非空即可。
    前端用可选框引导用户填风格/颜色/品类/店铺，note 为选填备注补充。

    衣橱功能（US-AT-16/17）：
    - wardrobeItemIds：用户从"我的衣橱"勾选的衣橱条目 ID（user_wardrobe.id），
      AgentService 会调 WardrobeClient 解析 itemType=1 条目对应的 itemId，
      拉取商品详情后强制注入节点2 候选池。
    - cartItemIds：用户购物车中的商品 id（可选，前端可勾选"加入推荐池"），
      用于"已加入购物车的商品"参与搭配。
    - orderItemIds：用户已购订单中的商品 id（可选），用于"已购风格"语义召回。
    - searchItemIds：用户通过搜索选定的商品 id（可选），用于"跨衣橱/购物车/订单外
      的平台商品"参与搭配。与 cartItemIds/orderItemIds 同为商品 ID，直接合并到候选池。
    四类 ID 在 AgentService._async_recommend 中合并去重为 state.wardrobe_item_ids（统一为商品 ID）。

    前端约束：
    - 同品类只能选 1 件（上衣/下装/全身套装/鞋/帽子/包/配饰互斥）
    - 全身套装与上衣/下装互斥（全身套装已覆盖上下身）
    - 全局上限 5 件（含四类来源合计）
    """
    styleTags: Optional[list[str]] = Field(None, description="风格标签列表（通勤/休闲/约会/运动/商务/街头/复古/欧美/亚洲）")
    color: Optional[list[str]] = Field(None, description="偏好色调列表（中文，如['白色','蓝色']），多选，should 加权非强制全品类同色")
    categories: Optional[list[str]] = Field(None, description="品类组合（上衣/下装/全身套装/鞋/帽子/包/配饰），不填则默认 [上衣,下装,鞋]。全身套装=成套衣服/连衣裙/连体衣/旗袍等成套衣物（一次 VTON 覆盖全身，等价于上衣+下装）；半身裙归下装")
    shopIds: Optional[list[int]] = Field(None, description="指定店铺 ID 列表（支持多选），不填则全平台")
    sceneDesc: Optional[str] = Field(None, description="场景描述（≤50字，如'下周面试'）")
    note: Optional[str] = Field(None, description="自然语言备注补充（≤50字），节点1 调 LLM 解析后合并到上述字段")
    photoSessionKey: Optional[str] = Field(None, description="照片会话 Key（用户上传真人照片后返回）")
    wardrobeItemIds: Optional[list[int]] = Field(None, description="我的衣橱条目 ID 列表（user_wardrobe.id），节点2 强制注入候选池")
    cartItemIds: Optional[list[int]] = Field(None, description="购物车商品 ID 列表，参与搭配召回")
    orderItemIds: Optional[list[int]] = Field(None, description="已购订单商品 ID 列表，用于'已购风格'召回")
    # 搜索单品（2026-07-28 新增）：用户在 AI 随心搭页面通过关键字+品类筛选搜索平台商品后选定的商品 ID 列表。
    # 与 cartItemIds/orderItemIds 一样直接是商品 ID（item.id），后端 _async_recommend 中合并到 merged_wardrobe_item_ids。
    # 前端约束：同品类只能选 1 件，全身套装与上衣/下装互斥，全局上限 5 件。
    searchItemIds: Optional[list[int]] = Field(None, description="通过搜索选定的商品 ID 列表，参与搭配召回（与 cartItemIds 同为商品 ID）")

    # ===== 性别与服装匹配=====
    # 用户在 AI 搭配页选定系统模特时传入，节点1 据此下载模特图作 VTON base，
    # 并用 systemModelGender 作为 target_gender 进行 Qdrant 性别过滤。
    # 优先级：systemModelId > photoSessionKey（用户自拍）> 无照片（走默认模特图）
    userBodyProfileId: Optional[int] = Field(None, description="用户身体信息档案 ID（衣橱页登记），节点1 拉取档案详情供 LLM 决策参考 + 尺码推荐")
    systemModelId: Optional[int] = Field(None, description="用户选定的系统模特图 ID，节点1 据此下载模特图作 VTON base")
    systemModelImageUrl: Optional[str] = Field(None, description="系统模特图 URL（前端从模特列表选中后传入，避免 Python 再调 Java）")
    systemModelGender: Optional[str] = Field(None, pattern="^(male|female)$",
                                              description="系统模特性别 male/female，节点1 直接用作 target_gender 进行 Qdrant 性别过滤")

    # ===== 天气服务=====
    # 前端通过浏览器 IP 定位获取用户城市名，传给后端用于天气查询
    # 留空时后端用默认城市"北京"兜底
    userCity: Optional[str] = Field(None, max_length=50,
                                     description="用户所在城市（前端 IP 定位获取），用于天气查询，留空走默认城市")
    userCountry: Optional[str] = Field(None, max_length=50,
                                        description="用户所在国家（前端 IP 定位获取），用于时尚趋势查询，留空走默认")


class AgentFeedbackRequest(BaseModel):
    """多轮反馈请求（核心功能设计 §3.3 + §3.7 点哪换哪 + §3.7' 反馈表单化 + §3.9 用户偏好 + §3.14 ReAct）

    用户对当前推荐结果不满意时提交反馈，ai-outfit 调用 LLM 解析后
    局部调整（替换某件单品/换风格/全部重来），同一会话内不重新扣配额。
    最大反馈轮次 3（首轮 + 2 轮反馈），超限返回 403。

    点哪换哪：
    - 前端每件单品旁加"换这个"按钮，点击时传 outfitIndex+itemIndex
    - 后端优先使用前端传入的索引（覆盖 LLM 解析结果），强制走 replace_single 分支
    - feedback 文本仍需传，用于 LLM 判断 action（如用户在备注里写"换颜色"）

    用户偏好反馈（US-AT-21/22）：
    - 前端表单勾选不喜欢的颜色/商品，比 LLM 解析更准确
    - dislikeColors 会累积到 user_dislike_colors，同会话内跨轮次持续生效
    - dislikeItemIds 仅本轮生效，下轮自动失效
    - retryVtonItemIds 仅本轮生效，商品本身 OK 但 VTON 效果差，触发单品重新换装（不换商品）
    - wantStyleTags 在节点1 合并到 style_tags，重新编码向量检索
    - 前端字段优先级 > LLM 解析（LLM 仅做备注兜底）

    自然语言备注（ReAct）：
    - note 非空时触发 ReAct Tool calling，LLM 自主调 update_user_preference/get_item_details/search_items
    - 适用于"第2套的鞋子太正式了，换休闲点的，顺便别推红色了"等复杂自然语言反馈
    - 前端结构化字段优先级 > ReAct 解析结果
    """
    taskId: str = Field(..., description="原推荐任务 ID")
    feedback: str = Field(..., min_length=1, max_length=200,
                          description="用户反馈原文，如'不喜欢这个颜色，换下装'（必填，可为占位符）")
    outfitIndex: Optional[int] = Field(None, ge=0, le=2,
                                        description="点哪换哪：搭配索引（0-based，0=第1套），由前端点击位置传入")
    itemIndex: Optional[int] = Field(None, ge=0, le=5,
                                      description="点哪换哪：单品索引（0-based），由前端点击位置传入")
    dislikeColors: Optional[list[str]] = Field(None,
                                                description="不喜欢的颜色（英文，如 ['red','pink']），同会话累积")
    dislikeItemIds: Optional[list[int]] = Field(None,
                                                 description="本轮不喜欢的商品 ID，仅本轮生效不累积")
    retryVtonItemIds: Optional[list[int]] = Field(None,
                                                   description="本轮 VTON 效果差的商品 ID（商品本身 OK，仅重新换装不换商品），仅本轮生效不累积")
    wantStyleTags: Optional[list[str]] = Field(None,
                                                description="想要追加的风格（如 ['休闲']），节点1 合并到 style_tags")
    note: Optional[str] = Field(None, max_length=200,
                                 description="自然语言备注补充（P2 ReAct）。非空时触发 ReAct Tool calling，"
                                             "LLM 自主调 update_user_preference/get_item_details/search_items。"
                                             "适用于'第2套鞋子太正式，换休闲点'等复杂反馈")


@router.post("/recommend", response_model=TaskResponse, summary="风格驱动模式推荐")
async def recommend(req: AgentRecommendRequest, request: Request):
    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        raise HTTPException(status_code=401, detail="无法识别用户身份，请先登录")

    # 必填校验：④ 风格驱动需要 styleTags/color/sceneDesc/note 任一非空；
    # ⑥ 用户选定模式（wardrobeItemIds/cartItemIds/orderItemIds/searchItemIds 非空）不需要风格字段
    is_user_picked = bool(req.wardrobeItemIds or req.cartItemIds or req.orderItemIds or req.searchItemIds)
    if not is_user_picked:
        if not (req.styleTags or req.color or req.sceneDesc or req.note):
            raise HTTPException(status_code=400,
                                detail="styleTags/color/sceneDesc/note 至少填一项")

    # 品类组合校验：全身套装与上衣/下装互斥，全局上限 5 件
    # 仅校验 categories 字段；衣橱/购物车/订单/搜索的商品品类在 AgentService 合并后校验
    if req.categories:
        try:
            validate_category_combination(req.categories)
        except CategoryConflictError as e:
            raise HTTPException(status_code=400, detail=e.details)

    # 调用 AgentService：配额预扣 → 写任务状态 → 启动异步 LangGraph 工作流
    agent_service = await get_agent_service()
    task_id, error_msg, error_code = await agent_service.recommend(
        user_id=user_id,
        style_tags=req.styleTags or [],
        scene_desc=req.sceneDesc,
        photo_session_key=req.photoSessionKey,
        color=req.color,
        categories=req.categories,
        shop_ids=req.shopIds,
        note=req.note,
        wardrobe_item_ids=req.wardrobeItemIds,
        cart_item_ids=req.cartItemIds,
        order_item_ids=req.orderItemIds,
        search_item_ids=req.searchItemIds,
        user_body_profile_id=req.userBodyProfileId,
        system_model_id=req.systemModelId,
        system_model_image_url=req.systemModelImageUrl,
        system_model_gender=req.systemModelGender,
        user_city=req.userCity,
        user_country=req.userCountry,
    )

    # 配额预扣被拒绝 → 按 error_code 映射 HTTP 状态码
    # - 429 并发限流（前一条搭配还在生成中）
    # - 403 credits 不足 / 配额服务不可用
    if error_msg:
        status_code = 429 if error_code == "CONCURRENT" else 403
        raise HTTPException(status_code=status_code, detail=error_msg)

    logger.info("推荐任务: taskId=%s, userId=%s, styleTags=%s, color=%s, shopIds=%s, "
                 "userPicked=%s, wardrobe=%s, cart=%s, order=%s, search=%s, "
                 "systemModelId=%s, systemModelGender=%s, bodyProfileId=%s, "
                 "userCity=%s, userCountry=%s",
                 task_id, user_id, req.styleTags, req.color, req.shopIds, is_user_picked,
                 req.wardrobeItemIds, req.cartItemIds, req.orderItemIds, req.searchItemIds,
                 req.systemModelId, req.systemModelGender, req.userBodyProfileId,
                 req.userCity, req.userCountry)
    return TaskResponse(taskId=task_id)


@router.post("/feedback", response_model=TaskResponse, summary="多轮反馈（每轮扣 credits）")
async def feedback(req: AgentFeedbackRequest, request: Request):
    """用户对推荐结果提交自然语言反馈，触发新一轮调整

    流程（核心功能设计 §3.3）：
      ① 读取原任务 state 快照 → ② LLM 解析反馈 → ③ 构造新一轮 initial_state
      → ④ 重新 ainvoke LangGraph 工作流（每轮扣 credits） → ⑤ WS 推送新结果

    同一 taskId 复用，前端通过 WS 收到新一轮 SUCCESS/FAILED 推送，
    或通过 round 字段区分轮次。最大反馈轮次 3（首轮 + 2 轮反馈）。
    """
    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        raise HTTPException(status_code=401, detail="无法识别用户身份，请先登录")

    if not req.feedback.strip():
        raise HTTPException(status_code=400, detail="feedback 不能为空")

    validate_task_id(req.taskId)  # H8: UUID 格式校验
    agent_service = await get_agent_service()
    task_id, error_msg, error_code = await agent_service.feedback(
        task_id=req.taskId,
        user_id=user_id,
        feedback=req.feedback,
        outfit_index=req.outfitIndex,
        item_index=req.itemIndex,
        dislike_colors=req.dislikeColors,
        dislike_item_ids=req.dislikeItemIds,
        retry_vton_item_ids=req.retryVtonItemIds,
        want_style_tags=req.wantStyleTags,
        note=req.note,
    )

    if error_msg:
        # 按 error_code 映射不同 HTTP 状态码（前端据此做差异化提示）：
        # - 404 任务不存在/已过期
        # - 409 任务已采纳终态（finished），不可再反馈
        # - 429 并发限流（分布式锁拒绝，前一条反馈正在处理）
        # - 403 轮次超限（最大 3 轮）
        # - 400 其他业务错误（解析失败/索引越界等）
        status_map = {
            "NOT_FOUND": 404,
            "FINISHED": 409,
            "CONCURRENT": 429,
            "ROUND_LIMIT": 403,
        }
        status_code = status_map.get(error_code or "", 400)
        raise HTTPException(status_code=status_code, detail=error_msg)

    logger.info("多轮反馈任务: taskId=%s, userId=%s, feedback=%s, outfitIdx=%s, itemIdx=%s, "
                 "dislikeColors=%s, dislikeItems=%s, retryVtonItems=%s, wantStyleTags=%s, note=%s",
                 task_id, user_id, req.feedback[:50], req.outfitIndex, req.itemIndex,
                 req.dislikeColors, req.dislikeItemIds, req.retryVtonItemIds, req.wantStyleTags,
                 req.note[:50] if req.note else None)
    return TaskResponse(taskId=task_id, msg="已收到反馈，正在调整")


@router.get("/result/{task_id}", response_model=TaskResultResponse,
            summary="查询风格驱动结果（兜底轮询）")
async def get_result(task_id: str, request: Request):
    """前端未收到 WS 推送时，用 taskId 轮询查询任务状态

    响应结构由 TaskResultResponse 约束（字段名稳定，前端可类型推断）：
    - status: PROCESSING / SUCCESS / FAILED / ACCEPTED
    - outfits: list[OutfitResult]，每套含 items / resultUrl / isPartialFailure
    - errorMsg: 失败原因
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


@router.get("/profile", summary="查询用户个性化推荐画像（前端展示用）")
async def get_profile(request: Request):
    """返回用户画像置信度 + 偏好风格/颜色 Top3，供前端展示个性化推荐状态

    失败容忍：画像聚合失败时返回空画像（confidence=0），前端不展示画像卡片
    """
    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        raise HTTPException(status_code=401, detail="无法识别用户身份，请先登录")
    try:
        from app.services.profile_service import get_profile_service
        profile_service = await get_profile_service()
        profile = await profile_service.get_or_load_profile(user_id)
        return {
            "profile_confidence": profile.get("profile_confidence", 0),
            "top_styles": (profile.get("top_styles") or [])[:3],
            "top_colors": (profile.get("top_colors") or [])[:3],
            "price_distribution": profile.get("price_distribution") or {},
        }
    except Exception as e:
        logger.warning("查询用户画像失败（返回空画像）: userId=%s, error=%s", user_id, e)
        return {"profile_confidence": 0, "top_styles": [], "top_colors": [], "price_distribution": {}}


# ============================================================
# v3 两阶段交互架构（AI 随心搭·风格驱动）
# ============================================================

class AgentSelectRequest(BaseModel):
    """v3 阶段二入口请求：用户选定阶段一 Top3 中的搭配子集后触发 VTON 生成

    场景：
      阶段一（POST /recommend）返回 Top3 候选搭配（resultUrl 为商品图）
      → 前端展示 3 套候选，用户勾选其中 1-3 套
      → 前端调 POST /select 触发阶段二 VTON 生成
      → 阶段二完成后前端收到 WS 推送 OUTFIT_VTON_RESULT
      → 用户对 VTON 效果图满意 → POST /accept 入库
    """
    parentTaskId: str = Field(..., description="阶段一 taskId（POST /recommend 返回的 taskId）")
    selectedOutfitIndexes: list[int] = Field(..., min_items=1, max_items=3,
                                              description="用户选定的搭配索引列表（Top3 中的 0/1/2 子集，至少 1 个，至多 3 个）")
    photoSessionKey: Optional[str] = Field(None,
                                            description="照片会话 Key（用户上传真人照片后返回）；"
                                                        "None 时回退用阶段一 photoSessionKey")


class AgentAcceptRequest(BaseModel):
    """v3 用户满意入库请求：用户在阶段二 VTON 结果中选 [满意-加购整套] 或 [满意-下单整套]

    场景：
      阶段二（POST /select）返回 VTON 效果图
      → 前端展示 VTON 效果图
      → 用户对某一套满意，选 [加购整套] 或 [下单整套]
      → 前端调 POST /accept 入库 ai_outfit_record 表
      → 后端调 Java OutfitController POST /items/admin/outfit/records 入库
    """
    taskId: str = Field(..., description="阶段二 VTON 任务 ID（POST /select 返回的 taskId）")
    outfitIndex: int = Field(..., ge=0, le=2,
                              description="用户满意的搭配索引（0-based，0=第1套）")
    acceptedAction: str = Field(..., pattern="^(cart|order)$",
                                 description="满意动作: cart（加购整套）/ order（下单整套）")
    # P0-1 尺码推荐（US-AT-48）：用户确认的尺码映射 {itemId: "L"}
    # 由前端 outfit-result.html 调 /items/size-chart/recommend-batch 后让用户确认得到
    # 透传到 Java 入库，后续购物车/订单页可从 record 读回
    sizeMap: dict[str, str] | None = Field(None, description="用户确认的尺码映射 {itemId: size}")


@router.post("/select", response_model=TaskResponse, summary="v3 阶段二：用户选定搭配 → VTON 生成")
async def select(req: AgentSelectRequest, request: Request):
    """v3 阶段二入口：用户选定阶段一 Top3 搭配子集后，触发 VTON 生成

    流程（v3 两阶段架构）：
      ① 读取阶段一 state 快照（parentTaskId）→ 取 outfit_candidates
      ② credits 预扣（OUTFIT_VTON，5×N credits，N=用户选定的搭配数）
      ③ 写任务状态 PROCESSING（新 taskId，stage="vton"）
      ④ 启动异步 VTON-only 工作流（仅 vton_generation + oss_upload 两个节点）
      ⑤ HTTP 返回 { taskId, status: "PROCESSING" }

    异步流：
      ⑥ VTON 生成（仅对 selectedOutfitIndexes 执行，60s 超时）
      ⑦ Redis 更新 SUCCESS/FAILED + WS 推送 OUTFIT_VTON_RESULT + MQ 通知 credits 确认/回滚

    v3.1 失败规则：
      - VTON 全部失败 → 全额 rollback credits
      - VTON 部分失败 → 不退还 credits（partial_failures 审计）
      - VTON API 故障 → 全额 rollback credits
    """
    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        raise HTTPException(status_code=401, detail="无法识别用户身份，请先登录")

    if not req.selectedOutfitIndexes:
        raise HTTPException(status_code=400, detail="请至少选定一套搭配")

    validate_task_id(req.parentTaskId)  # H8: UUID 格式校验
    agent_service = await get_agent_service()
    task_id, error_msg, error_code = await agent_service.select(
        parent_task_id=req.parentTaskId,
        user_id=user_id,
        selected_outfit_indexes=req.selectedOutfitIndexes,
        photo_session_key=req.photoSessionKey,
    )

    if error_msg:
        # 按 error_code 映射不同 HTTP 状态码
        # - 404 阶段一任务不存在/已过期
        # - 409 阶段一任务尚未完结
        # - 400 索引越界
        # - 403 credits 不足
        # - 429 并发限流
        status_map = {
            "NOT_FOUND": 404,
            "NOT_FINISHED": 409,
            "BAD_INDEX": 400,
            "CONCURRENT": 429,
        }
        status_code = status_map.get(error_code or "", 403)
        raise HTTPException(status_code=status_code, detail=error_msg)

    logger.info("阶段二 VTON 任务: taskId=%s, parentTaskId=%s, userId=%s, selected=%s",
                 task_id, req.parentTaskId, user_id, req.selectedOutfitIndexes)
    return TaskResponse(taskId=task_id)


@router.post("/accept", summary="v3 用户满意入库")
async def accept(req: AgentAcceptRequest, request: Request):
    """v3 用户满意入库：用户在阶段二 VTON 结果中选 [满意-加购整套] 或 [满意-下单整套]

    流程：
      ① 读取阶段二 state 快照 → 取 final_outfits[outfitIndex]
      ② 构造 AiOutfitRecordCreateDTO → 调 Java OutfitController POST /items/admin/outfit/records 入库
      ③ 标记任务 finished=True，阻止再次反馈
      ④ O3：异步记录搭配事件到 Qdrant（EpisodicMemory）
      ⑤ WS 推送 OUTFIT_ACCEPTED 通知

    返回：
      - 成功：{ recordId, taskId, outfitIndex, acceptedAction }
      - 失败：按 error_code 映射 HTTP 状态码
    """
    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        raise HTTPException(status_code=401, detail="无法识别用户身份，请先登录")

    validate_task_id(req.taskId)  # H8: UUID 格式校验
    agent_service = await get_agent_service()
    task_id, error_msg, error_code = await agent_service.accept(
        task_id=req.taskId,
        user_id=user_id,
        outfit_index=req.outfitIndex,
        accepted_action=req.acceptedAction,
        size_map=req.sizeMap,
    )

    if error_msg:
        # 按 error_code 映射不同 HTTP 状态码
        # - 429 并发限流（正在处理采纳请求）
        # - 404 任务不存在/已过期
        # - 409 任务尚未完成 或 已采纳
        # - 400 索引越界 或 acceptedAction 不合法
        status_map = {
            "NOT_FOUND": 404,
            "NOT_FINISHED": 409,
            "FINISHED": 409,
            "CONCURRENT": 429,
            "BAD_INDEX": 400,
            "BAD_ACTION": 400,
        }
        status_code = status_map.get(error_code or "", 400)
        raise HTTPException(status_code=status_code, detail=error_msg)

    logger.info("用户满意入库: taskId=%s, userId=%s, outfitIdx=%s, action=%s",
                 task_id, user_id, req.outfitIndex, req.acceptedAction)
    return {
        "taskId": task_id,
        "status": "ACCEPTED",
        "outfitIndex": req.outfitIndex,
        "acceptedAction": req.acceptedAction,
    }


# ============================================================
# 性别与服装匹配：系统模特列表 + 身体信息档案
# ============================================================
@router.get("/system-models", summary="查询系统模特图列表（用户端，支持性别过滤）")
async def list_system_models(
    request: Request,
    gender: Optional[str] = None,
    page: int = 1,
    size: int = 50,
):
    """用户端查询系统模特图列表（性别过滤扩展）

    场景：
      用户在 AI 随心搭页选"使用系统模特"时，前端调本接口拉模特列表，
      展示男/女模特卡片，用户选定后传 systemModelId/systemModelImageUrl/systemModelGender
      到 POST /recommend 触发搭配生成。

    性别过滤：
      - gender=male：只返回男模特
      - gender=female：只返回女模特
      - gender 不传：返回全部（前端可客户端过滤）

    实现：转发到 Java AiModelController#listSystemImages（/items/admin/ai-model/system-images），
    Java 端已对该接口做了 isActive=1 过滤，仅返回上架模特图。

    返回：{ list: [...SystemModelImageDTO], total, pages }
    """
    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        raise HTTPException(status_code=401, detail="无法识别用户身份，请先登录")

    if gender is not None and gender not in ("male", "female"):
        raise HTTPException(status_code=400, detail="gender 必须为 male 或 female")

    java_client = await get_java_client()
    data = await java_client.list_system_model_images(
        user_id=user_id, gender=gender, page=page, size=size,
    )
    if data is None:
        raise HTTPException(status_code=503, detail="模特图服务暂时不可用，请稍后重试")
    return data

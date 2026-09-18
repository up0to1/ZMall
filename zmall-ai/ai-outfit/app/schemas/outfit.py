"""
AI 随心搭搭配结果数据模型（Pydantic v2）

统一字段命名（全部 camelCase 对齐前端）：
  - 单品：itemId / name / image / category / color / price / shopId / shopName
  - 搭配：items / resultUrl / reason / score / isPartialFailure / isVtonGenerated / isSelected
  - 任务结果：status / taskId / userId / taskType / stage / outfits / errorMsg / finishedAt
  - WS 消息：type / taskId / status / stage / outfits / errorMsg

字段名历史问题：
  - 节点2 候选商品用 snake_case（item_id / shop_id），节点3 输出时转 camelCase
  - 节点1.5 用户选定搭配仍用 snake_case，导致 final_outfits 字段名不一致
  - 前端 it.image || it.imageUrl 兜底就是字段名混乱的产物
  现统一为 camelCase，由 OutfitItem 模型强制约束。
"""
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class OutfitItem(BaseModel):
    """搭配单品（节点3/5/Java DTO 共用）

    字段名对齐前端 outfit-result.html / outfit-history.html 的消费方式：
    it.itemId / it.name / it.image / it.category / it.color / it.price / it.shopId
    """
    model_config = ConfigDict(
        # 兼容节点输出中遗留的 snake_case 字段（item_id / shop_id），
        # Pydantic 自动转 camelCase 后消费
        populate_by_name=True,
        extra="allow",   # 允许额外字段透传（避免节点临时字段被丢弃）
    )

    itemId: Optional[int] = None
    name: str = ""
    image: Optional[str] = None       # 统一字段名（不再 image / imageUrl 混用）
    category: Optional[str] = None
    color: Optional[str] = None
    price: float = 0.0
    shopId: Optional[int] = None
    shopName: Optional[str] = None
    isWardrobePicked: bool = False
    isMain: bool = False              # 商品驱动模式主商品标记
    # 以下字段为审计/可解释性用，前端可忽略
    crossShop: bool = False
    colorConstraintRelaxed: bool = False  # 明确颜色候选不足时，检索已降级为软偏好
    inventoryUnknown: bool = False       # 实时库存查询失败/部分未知，购买前需再次校验
    score: float = 0.0
    styleTags: list[str] = Field(default_factory=list)
    itemGender: Optional[str] = None


class OutfitResult(BaseModel):
    """单套搭配结果（含 VTON 效果图）

    节点5 oss_upload 构造 final_outfits 时使用此模型；
    _on_success 推送 WS / Redis 时序列化此模型；
    _auto_save_records 入库时用此模型字段映射 Java DTO。
    """
    model_config = ConfigDict(extra="allow")

    items: list[OutfitItem] = Field(default_factory=list)
    resultUrl: Optional[str] = None    # None=VTON 失败，前端展示"生成失败"
    reason: str = ""
    score: float = 0.0
    isVtonGenerated: bool = False      # True=VTON 生成，False=商品图兜底/失败
    isSelected: bool = True            # 阶段二未选定的搭配为 False
    isPartialFailure: bool = False     # 部分单品 VTON 失败标记
    vtonQualityStatus: Optional[str] = None  # passed / warning / unverified
    vtonWarning: Optional[str] = None        # 仅高置信不一致时展示
    vtonQualityIssues: list[str] = Field(default_factory=list)


class TaskResultResponse(BaseModel):
    """GET /result/{taskId} 响应（替代裸 dict）

    Python _on_success 写入 Redis 的 JSON 结构；
    前端轮询接口直接返回此模型，字段稳定可类型推断。
    """
    model_config = ConfigDict(extra="allow")

    status: str                        # PROCESSING / SUCCESS / FAILED / ACCEPTED
    taskId: str
    userId: Optional[int] = None
    taskType: Optional[str] = None     # OUTFIT_AGENT / OUTFIT_PRODUCT / OUTFIT_RECOMMEND / OUTFIT_VTON
    stage: Optional[str] = None        # recommend / vton / None
    outfits: list[OutfitResult] = Field(default_factory=list)
    errorMsg: Optional[str] = None
    finishedAt: Optional[str] = None


class WsOutfitMessage(BaseModel):
    """WS 推送消息（_ws_push 用）

    前端 ai-outfit-ws.js 按 msg.type 过滤消息：
    - OUTFIT_VTON_RESULT：阶段二 VTON 完成
    - OUTFIT_RECOMMEND_RESULT：阶段一候选推荐完成
    - OUTFIT_AGENT：单阶段/反馈轮完成
    - OUTFIT_PRODUCT：商品驱动完成
    - OUTFIT_ACCEPTED：用户已采纳
    - OUTFIT_AGENT_FEEDBACK：反馈轮已采纳
    """
    model_config = ConfigDict(extra="allow")

    type: str
    taskId: str
    status: str                        # SUCCESS / FAILED / ACCEPTED
    stage: Optional[str] = None
    outfits: list[OutfitResult] = Field(default_factory=list)
    errorMsg: Optional[str] = None


class OutfitRecordDTO(BaseModel):
    """Python ai-outfit → Java item-service 入库 DTO

    字段名严格对齐 Java AiOutfitRecordCreateDTO，
    避免 _auto_save_records 中手动对齐字段名。
    """
    taskId: str
    userId: int
    round: Optional[int] = 1
    outfitIndex: int
    outfitJson: str                    # OutfitResult 序列化后的 JSON 字符串
    vtonResultUrl: Optional[str] = None  # None=VTON 失败，Java DTO 已放宽校验
    userPhotoUrl: Optional[str] = None
    modelImageSource: Optional[str] = None
    modelImageId: Optional[int] = None
    systemModelImageUrl: Optional[str] = None  # 用户选定的初始模特图 URL（衣橱"模特/原始照片"展示用）
    acceptedAction: str = "pending"    # cart / order / pending / rejected / saved
    accepted: int = 0                  # 0=未采纳 / 1=已采纳
    creditsConsumed: Optional[int] = None

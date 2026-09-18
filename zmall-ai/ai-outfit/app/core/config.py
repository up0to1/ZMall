"""
ai-outfit 配置（AI 随心搭服务）
"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    port: int = 9001

    nacos_server: str = "192.168.59.128:8848"
    nacos_username: str = ""
    nacos_password: str = ""

    redis_host: str = "192.168.59.128"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str = ""

    qdrant_host: str = "192.168.59.128"
    qdrant_port: int = 6333
    qdrant_api_key: str = ""
    qdrant_prefix: str = ""
    # Qdrant 向量检索相似度阈值参数化
    # CLIP v2 实测分布 0.2-0.4，原硬编码 0.5 偏严导致召回不足。默认 0.3，可按线上实测热调
    qdrant_score_threshold: float = 0.3

    rabbitmq_host: str = "192.168.59.128"
    rabbitmq_port: int = 5672
    rabbitmq_username: str = "hmall"
    rabbitmq_password: str = ""
    # 与 Java 侧 shared-rabbitmq.yaml 的 virtual-host 保持一致（默认 /hmall）
    rabbitmq_vhost: str = "/hmall"

    # ===== MySQL（对账脚本 reconcile_mysql_qdrant.py 使用，主流程不依赖）=====
    # 补充 mysql_* 字段，否则对账脚本 settings.mysql_* 引用崩溃
    # 与 item-service 的 hm.db.database 对齐，使用 hm-item 库
    # （item-service 通过 Nacos shared-jdbc.yaml 用 ${hm.db.database:hmall} 注入 datasource）
    mysql_host: str = "192.168.59.128"
    mysql_port: int = 3306
    mysql_username: str = "root"
    mysql_password: str = "123456"
    mysql_database: str = "hm-item"

    oss_endpoint: str = ""
    oss_access_key_id: str = ""
    oss_access_key_secret: str = ""
    oss_bucket_name: str = "zmall-ai"

    # ===== nginx 静态资源根目录（图片本地降级存储 + 前端访问 URL 前缀）=====
    # 项目部署到服务器或 GitHub 共享时，需通过环境变量覆盖此路径
    # 模特图 OSS 降级和本地图片都写到该目录下
    # 前端通过 nginx 静态映射访问：location /uploads/ → root html/
    nginx_uploads_root: str = ""
    nginx_uploads_url_prefix: str = "/uploads"

    # ===== nginx 外部访问 base URL（Python 下载本地存储的图片用）=====
    # Java item-service FileStorageStrategy 本地模式存的是相对路径（如 /uploads/model-images/xxx.jpg），
    # Python ai-outfit 拉到这种相对路径后需要拼接完整 URL 才能下载。
    # 配置示例：http://192.168.59.128:18080（用户端 nginx）；留空时尝试走 Nacos 发现的 item-service URL 拼接
    nginx_external_base_url: str = ""

    # ===== 文本向量编码（阿里 DashScope text-embedding-v4）=====
    # 留空时使用 EmbedClient 默认 endpoint；向量维度为 1024
    embed_api_url: str = ""
    embed_api_key: str = ""

    # ===== LLM 配置（OpenAI 兼容协议，未配置时走规则降级解析）=====
    # 同时也是千问 DashScope API Key 的来源（qwen_* 配置复用此 Key）
    # 场景 A（用户未上传自拍照）：用纯文本模型做搭配决策
    # 场景 B（用户上传自拍照）：用图像理解模型分析用户照片 + 搭配决策
    llm_api_url: str = ""
    llm_api_key: str = ""
    # 向后兼容字段（等价于 llm_text_model）
    llm_model: str = "qwen3.5-flash"
    # 纯文本任务模型（HyDE 改写 / note 解析 / 反馈解析 / 搭配选择 / Reflection 自检）
    # 从 qwen-flash 升级到 qwen3.5-flash，提升搭配决策/反馈解析准确率
    # qwen3.5-flash 是全模态模型，文本能力比 qwen-flash 强，支持思考模式
    llm_text_model: str = "qwen3.5-flash"
    # 图像理解模型（分析用户自拍照的肤色/性别/风格倾向，场景 B 关键）
    # 推荐 qwen3.5-flash：https://www.qianwenai.com/models/qwen3.5-flash（原生视觉理解 + 函数调用）
    llm_vision_model: str = "qwen3.5-flash"
    # 纯文本任务统一用 qwen3.5-flash（含 react_intent / react_feedback 的 ReAct 工具调用决策）
    # 撤销 tongyi-intent-detect-v3 方案（该模型为单轮意图分类，不支持多轮 ReAct 循环和 JSON 输出）

    # ===== 千问 DashScope API 配置=====
    # 文档：
    #   - VTON plus: https://help.aliyun.com/zh/model-studio/developer-reference/ai-try-on
    #   - VTON 精修: https://help.aliyun.com/zh/model-studio/developer-reference/ai-try-on-refiner
    #   - Wan 2.7:   https://help.aliyun.com/zh/model-studio/developer-reference/image-edit-wan2-7
    # API Key 复用 llm_api_key（同一阿里百炼账号）
    qwen_api_url: str = "https://dashscope.aliyuncs.com/api/v1"
    # 虚拟换装模型（aitryon-plus 比 aitryon 清晰度更高、纹理还原更好，耗时更长）
    qwen_vton_model: str = "aitryon-plus"
    # 虚拟换装后精修模型（对 VTON 结果二次生成，提升还原度）
    qwen_refiner_model: str = "aitryon-refiner"
    # 是否启用 VTON 后精修（用户反馈"精修/还原度低/效果不真实"时触发）
    qwen_refiner_enabled: bool = True
    # 虚拟穿戴 / 人物动作微调模型（wan2.7-image，注意不使用 pro 版本）
    # 用途 1：配饰/包类的穿戴生成（VTON 不支持这些品类）
    # 用途 2：AI 模特功能的人物姿势微调（保持主体不变，修改姿势/光影）
    qwen_wan_model: str = "wan2.7-image"

    # ===== 系统默认模特图（场景 A：用户未上传自拍照时 VTON 兜底）=====
    # v2 统一系统模特图池：优先调 Java item-service /items/admin/ai-model/system-images/random-default
    # 该字段作为 Java API 不可用时的最后兜底（直接下载指定 URL 的图片）
    # 推荐尺寸：768x1024（与千问 VTON 输入对齐），白底，正面全身照
    # 留空且 Java API 不可用且 AI 生成也失败时，场景 A 的 VTON 会降级为商品白底图 PIL 堆叠（体验差）
    default_model_image_url: str = ""

    # ===== 多轮反馈最大轮次（首轮 + 反馈轮，超限强制结束）=====
    feedback_max_rounds: int = 3

    # ===== 外部 API 代理（可选）=====
    # 配置后 LLM 与文本向量客户端会通过此代理访问模型服务（包括 DashScope）
    # 留空则直连
    proxy_url: str = ""

    # ===== v6 工具拓展配置=====
    # 工具总开关：关闭后所有外部工具不可用，回归纯 LLM 推理
    # 开启后天气/库存/价格工具按各自独立开关启用
    external_tools_enabled: bool = True

    # 各工具独立开关（默认关闭，按需开启）
    weather_tool_enabled: bool = True         # 天气/季节服务（阶段2）
    trend_tool_enabled: bool = False          # 流行趋势服务（阶段3，平台销量数据源，已被 fashion_trend 替代，保留向后兼容）
    fashion_trend_tool_enabled: bool = True   # 时尚潮流搜索服务（AnySearch API，社媒+通用搜索）
    inventory_tool_enabled: bool = True       # 实时库存查询（阶段1）
    price_tool_enabled: bool = True           # 价格平衡分析（本地实现，默认开）

    # 工具默认超时和熔断参数
    tool_default_timeout: float = 5.0
    tool_failure_threshold: int = 3       # 连续失败 N 次后熔断
    tool_recovery_minutes: int = 5        # 熔断恢复时间（分钟）

    # 天气服务配置（阶段2，uapis.cn API）
    # API Key 以 uapi- 开头，从 https://uapis.cn 控制台获取
    # 鉴权方式：Authorization: Bearer <KEY>
    weather_api_key: str = ""
    weather_default_city: str = "北京"     # 默认城市（用户未提供时使用）
    weather_api_url: str = "https://uapis.cn/api/v1/misc/weather"

    # 流行趋势服务配置（阶段3，旧版基于平台销量，已被 fashion_trend 替代）
    trend_lookback_days: int = 30         # 销量回溯天数
    trend_top_k: int = 50                 # 每品类返回 Top K 商品
    trend_cluster_k: int = 3              # 风格聚类数（K-means）

    # 时尚潮流搜索服务配置（2026-07-31 新增，基于 AnySearch API）
    # AnySearch 是海外服务，走 settings.proxy_url 代理（与 Jina 一致）
    # API Key 以 as_sk_ 开头，从 https://www.anysearch.com 控制台获取
    # 鉴权方式：Authorization: Bearer <KEY>
    anysearch_api_key: str = ""
    anysearch_api_url: str = "https://api.anysearch.com/v1/search"
    anysearch_max_results: int = 5          # 每个 tag 返回数量（social + general 各 5 条）
    # 缓存 TTL（秒），潮流更新不频繁，默认 600s
    fashion_trend_cache_ttl: int = 600

    # 库存服务配置（阶段1）
    inventory_threshold: int = 0          # 库存阈值，0 表示 >0 才算有库存
    inventory_min_candidates: int = 3     # 过滤后候选不足 N 件时触发跨店补全

    # ===== 子 Agent 配置=====
    # 意图理解子 Agent：用 ReAct 模式让 LLM 自主决定调用 parse_note/HyDE/weather/photo/encode
    # 已固定启用（原 intent_agent_enabled 开关已移除，始终走 ReAct 子 Agent）
    # 反馈轮仍走原节点1 硬编码顺序（feedback_parsed 非空时跳过子 Agent）
    intent_agent_max_rounds: int = 5       # ReAct 最大循环轮次

    # 价格平衡配置（阶段1）
    price_balance_ratio_max: float = 5.0  # 价格倍数阈值（≥5 视为不平衡）

    # ===== 全局工作流并发限制（2026-08-06 新增）=====
    # 同时运行的 LangGraph 生成工作流数量上限，防止 LLM/VTON 等外部 API 并发打满
    workflow_max_concurrent: int = 4
    # 等待并发槽位的超时（秒），超时返回"系统繁忙"（用户稍后重试）
    # 默认 600s = 单个任务最大超时（estimate_vton_timeout 上限 MAX_TIMEOUT_SECONDS，
    # 对应全局上限 5 个品类全部走 VTON 的最坏情况），确保排在后面的任务能等到
    # 前一个任务跑完，而不是中途被误杀
    workflow_slot_wait: float = 600.0

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()

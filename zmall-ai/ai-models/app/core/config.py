"""
ai-models 配置（AI 模特图服务）

从环境变量读取配置（支持 Nacos 配置中心后续扩展）。
"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """ai-models 配置项"""

    # ===== 服务配置 =====
    port: int = 9000

    # ===== Nacos =====
    nacos_server: str = "192.168.59.128:8848"
    nacos_username: str = ""
    nacos_password: str = ""

    # ===== Redis =====
    redis_host: str = "192.168.59.128"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str = ""

    # ===== Qdrant =====
    qdrant_host: str = "192.168.59.128"
    qdrant_port: int = 6333
    qdrant_api_key: str = ""
    qdrant_prefix: str = ""
    # Qdrant 向量检索相似度阈值参数化（与 ai-outfit 对齐）
    qdrant_score_threshold: float = 0.3

    # ===== RabbitMQ =====
    rabbitmq_host: str = "192.168.59.128"
    rabbitmq_port: int = 5672
    rabbitmq_username: str = "hmall"
    rabbitmq_password: str = "123456"
    # 与 Java 侧 shared-rabbitmq.yaml 的 virtual-host 保持一致（默认 /hmall）
    rabbitmq_vhost: str = "/hmall"

    # ===== MySQL（与其他服务对齐，预留扩展）=====
    # 与 item-service 的 hm.db.database 对齐，使用 hm-item 库
    mysql_host: str = "192.168.59.128"
    mysql_port: int = 3306
    mysql_username: str = "root"
    mysql_password: str = ""
    mysql_database: str = "hm-item"

    # ===== OSS =====
    oss_endpoint: str = ""
    oss_access_key_id: str = ""
    oss_access_key_secret: str = ""
    oss_bucket_name: str = "zmall-ai"

    # ===== nginx 静态资源根目录（图片本地降级存储 + 前端访问 URL 前缀）=====
    # 项目部署到服务器或 GitHub 共享时，需通过环境变量覆盖此路径
    # 模特图 OSS 降级时写到该目录下，爬虫图片也走此机制
    # 前端通过 nginx 静态映射访问：location /uploads/ → root html/
    nginx_uploads_root: str = ""
    nginx_uploads_url_prefix: str = "/uploads"

    # ===== nginx 外部访问 base URL（Python 下载 Java 存储的相对路径图片用）=====
    # Java item-service 存的是相对路径（如 /uploads/model-images/xxx.jpg），
    # Python ai-models 拉到这种相对路径后需要拼接完整 URL 才能下载。
    # 配置示例：http://localhost:18080（本地 Windows nginx）；留空时尝试走 Nacos 发现的 item-service URL 拼接
    nginx_external_base_url: str = ""

    # ===== LLM 配置（多 Agent 决策用，OpenAI 兼容协议）=====
    # 多 Agent 工作流在 ai-models 内部执行（不再跨服务调 ai-outfit）
    # - 策划阶段（衣品审美 EU/Asia + 摄影师 + 导演汇总）：纯文本，用 llm_text_model
    # - 评估阶段（5 角色 Vision 评估）：图像理解，用 llm_vision_model
    # 留空时所有 LLM 调用走规则降级（功能可用但效果降低）
    # 推荐：阿里百炼平台 https://bailian.console.aliyun.com/
    #   - llm_text_model=qwen3.5-flash（全模态，文本能力强，支持思考模式）
    #   - llm_vision_model=qwen3.5-flash（原生视觉理解）
    llm_api_url: str = ""
    llm_api_key: str = ""
    llm_text_model: str = "qwen3.5-flash"
    llm_vision_model: str = "qwen3.5-flash"

    # ===== 千问 DashScope API 配置 =====
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
    # 虚拟穿戴 / 人物动作微调模型（wan2.7-image，注意不使用 pro 版本）
    # 用途 1：配饰/包类的穿戴生成（VTON 不支持这些品类）
    # 用途 2：AI 模特功能的人物姿势微调（保持主体不变，修改姿势/光影）
    qwen_wan_model: str = "wan2.7-image"

    # 图像向量编码（Jina CLIP v2，/api/v1/search/similar 接口用）
    embed_api_url: str = ""
    embed_api_key: str = ""

    # ===== 代理（海外 API 走代理）=====
    # Jina API 和 Qdrant Cloud 在海外，需要代理
    # 可灵 API 和阿里百炼是国内服务，不走代理
    # 留空则不启用代理
    proxy_url: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()

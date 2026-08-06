"""
AI 模特图生成服务

设计文档 §1.0 §1.3：
  - 输入：模特图（三级池解析后的 URL）+ 1-4 件商品图（按链式顺序排好）
  - 输出：N 张中间图 + 1 张最终图（每件商品穿上后的图都上传 OSS）
  - 模型：VtonClient.try_on_chain_with_intermediates
  - 兜底：VTON 全部失败时返回失败，由调用方降级处理

链式顺序（由 Java 侧解析后传入，Python 不重新排序）：
  全身套装 → 上衣 → 下装 → 帽子
"""
import asyncio
import hashlib
import logging
from pathlib import Path

import httpx

from shared.model_client.vton_client import VtonClient
from shared.oss_client.uploader import OssUploader
from shared.oss_client.client import OssClientWrapper
from shared.outfit_common import is_safe_image_url
from app.core.config import settings

logger = logging.getLogger(__name__)

# 模特图 OSS 降级时子目录名（拼接在 settings.nginx_uploads_root 后）
LOCAL_FALLBACK_SUBDIR = "model"


def _get_local_fallback_dir() -> Path | None:
    """获取本地降级存储目录（从配置读取，避免写死路径）

    路径 = settings.nginx_uploads_root / model
    若 nginx_uploads_root 未配置，返回 None（降级不可用）
    """
    root = settings.nginx_uploads_root
    if not root:
        return None
    return Path(root) / LOCAL_FALLBACK_SUBDIR


def _get_local_fallback_url_prefix() -> str:
    """获取本地降级存储的 URL 前缀（从配置读取）"""
    return f"{settings.nginx_uploads_url_prefix.rstrip('/')}/{LOCAL_FALLBACK_SUBDIR}"


class ModelService:
    """AI 模特图生成服务（多商品链式 VTON）"""

    def __init__(self):
        self._vton_client: VtonClient | None = None
        self._oss_uploader: OssUploader | None = None

    @property
    def vton_client(self) -> VtonClient:
        """懒加载 VtonClient（千问 aitryon-plus，复用 qwen_api_url + llm_api_key + OssUploader）"""
        if self._vton_client is None:
            self._vton_client = VtonClient(
                api_url=settings.qwen_api_url,
                api_key=settings.llm_api_key,
                model=settings.qwen_vton_model,
                oss_uploader=self.oss_uploader,
            )
        return self._vton_client

    @property
    def oss_uploader(self) -> OssUploader:
        if self._oss_uploader is None:
            wrapper = OssClientWrapper(
                endpoint=settings.oss_endpoint,
                access_key_id=settings.oss_access_key_id,
                access_key_secret=settings.oss_access_key_secret,
                bucket_name=settings.oss_bucket_name,
            )
            self._oss_uploader = OssUploader(wrapper)
        return self._oss_uploader

    async def generate_model_images_chain(
        self,
        task_id: str,
        model_image_url: str,
        items: list[dict],
    ) -> tuple[bool, list[str] | None, list[str] | None, str | None]:
        """AI 模特图生成（多商品链式 VTON + 中间图输出）

        Args:
            task_id: 任务ID
            model_image_url: 模特图 OSS URL（Java 侧已从三级池解析好）
            items: 商品列表（按链式顺序排好），每个 item 含：
                   - itemId: 商品ID
                   - ossUrl: 商品白底图 OSS URL
                   - category: 品类（中文，用于日志和文件名）
        Returns:
            (success, result_urls, item_categories, error_msg)
            - success: 是否成功（至少 1 张图生成）
            - result_urls: N 张中间图+最终图 OSS URL 列表
            - item_categories: 各图对应的品类（前端标注用）
            - error_msg: 失败原因
        """
        logger.info("开始链式VTON模特图生成: taskId=%s, 商品数=%d",
                    task_id, len(items))

        # 1. 下载模特图（base）
        model_image = await self._download_image(model_image_url)
        if model_image is None:
            return False, None, None, "模特图下载失败"

        # 2. 下载所有商品图（按链式顺序）
        garment_images: list[bytes] = []
        item_categories: list[str] = []
        for idx, item in enumerate(items):
            garment = await self._download_image(item.get("ossUrl", ""))
            if garment is None:
                logger.warning("商品%d图下载失败，跳过: itemId=%s",
                               idx + 1, item.get("itemId"))
                continue
            garment_images.append(garment)
            item_categories.append(item.get("category", "未知"))

        if not garment_images:
            return False, None, None, "所有商品图下载失败"

        # 3. 链式 VTON（含中间图输出）
        try:
            intermediate_images = await self.vton_client.try_on_chain_with_intermediates(
                user_photo=model_image,
                garments=garment_images,
                max_retries_per_item=1,  # 链式场景每件 1 次重试
            )
        except Exception as e:
            logger.error("链式VTON调用异常: taskId=%s, error=%s", task_id, e, exc_info=True)
            return False, None, None, f"链式VTON调用异常: {e}"

        if not intermediate_images:
            return False, None, None, "链式VTON全部失败（所有商品穿上效果均生成失败）"

        # 4. 上传所有中间图+最终图到 OSS
        # 文件名：{taskId}_{step}_{category}.jpg（如 abc123_1_tops.jpg）
        # intermediate_images 是 [(image, original_idx), ...]，original_idx 是
        # garments 中的下标。必须用该下标对齐 item_categories，禁止用
        # item_categories[:len(intermediate_images)] 从头部截取——中间件失败 continue 后
        # intermediate_images 长度 < item_categories，头部截取会让品类标签与图片错位。
        # 例: 商品[上衣,下装,帽子]，下装失败 → intermediate_images=[上衣图,帽子图]，
        #     截取得 [上衣,下装]（错），按下标得 [上衣,帽子]（对）。
        result_urls: list[str] = []
        successful_categories: list[str] = []
        for step, (image_data, garment_idx) in enumerate(intermediate_images, start=1):
            # garment_idx 对应 garment_images 中的下标，与 item_categories 一一对齐
            category = item_categories[garment_idx] if garment_idx < len(item_categories) else "未知"
            successful_categories.append(category)
            url = await asyncio.to_thread(
                self._upload_image_with_fallback,
                image_data,
                task_id,
                step,
                category,
            )
            if url is None:
                logger.error("第%d张图上传OSS和本地降级均失败，跳过", step)
                continue
            result_urls.append(url)

        if not result_urls:
            return False, None, None, "所有图上传OSS失败"

        logger.info("链式VTON模特图生成成功: taskId=%s, 输出%d张图",
                    task_id, len(result_urls))
        return True, result_urls, successful_categories, None

    async def _download_image(self, url: str) -> bytes | None:
        """下载图片

        支持 Java 侧存储的相对路径（如 /uploads/model-images/xxx.jpg）：
        检测到相对路径时，拼接 settings.nginx_external_base_url 形成完整 URL。

        注意：必须用 trust_env=False 禁用系统代理，否则 Windows 系统代理
        （如 Clash 127.0.0.1:7897）会拦截 localhost 请求导致 502。
        """
        if not url:
            return None
        # 相对路径拼接：Java item-service 存的是 /uploads/xxx.jpg，Python 需补全 host
        if url.startswith("/"):
            base = settings.nginx_external_base_url.rstrip("/")
            if not base:
                logger.error("图片URL是相对路径但 nginx_external_base_url 未配置: url=%s", url[:100])
                return None
            url = f"{base}{url}"
        # A2 SSRF 防护：拦截内网/回环/元数据地址
        if not is_safe_image_url(url):
            logger.warning("SSRF 拦截: 非法图片 URL 已拒绝: %s", url[:120])
            return None
        async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
            try:
                resp = await client.get(url)
                if resp.status_code == 200:
                    return resp.content
                logger.error("图片下载失败: url=%s, status=%s",
                             url[:100], resp.status_code)
                return None
            except Exception as e:
                logger.error("图片下载异常: url=%s, error=%s", url[:100], e)
                return None

    def _upload_image_with_fallback(
        self,
        image_data: bytes,
        task_id: str,
        step: int,
        category: str,
    ) -> str | None:
        """上传图片到 OSS，失败时降级到本地 nginx 静态目录

        文件名规则：{taskId}_{step}_{category}.jpg
        目录：model/{taskId}/
        """
        # OSS 上传
        try:
            url = self.oss_uploader.upload_image(
                file_data=image_data,
                directory=f"model/{task_id}",
                file_ext="jpg",
            )
            if url is not None:
                return url
        except Exception as e:
            logger.warning("OSS上传异常，降级到本地: step=%d, error=%s", step, e)

        # 本地降级
        return self._save_to_local(image_data, task_id, step, category)

    @staticmethod
    def _save_to_local(
        image_data: bytes,
        task_id: str,
        step: int,
        category: str,
    ) -> str | None:
        """OSS 降级时把图片落地到 nginx 静态目录

        文件命名：{taskId}_{step}_{category}_{md5前8位}.jpg
        返回 nginx 访问 URL（/uploads/model/xxx.jpg）

        若 NGINX_UPLOADS_ROOT 未配置，返回 None（降级不可用）
        """
        local_dir = _get_local_fallback_dir()
        if local_dir is None:
            logger.error("NGINX_UPLOADS_ROOT 未配置，无法本地降级存储")
            return None
        local_dir.mkdir(parents=True, exist_ok=True)
        md5_prefix = hashlib.md5(image_data).hexdigest()[:8]
        # category 可能含中文，文件名用英文映射避免编码问题
        safe_category = _category_to_filename_safe(category)
        filename = f"{task_id}_{step}_{safe_category}_{md5_prefix}.jpg"
        local_path = local_dir / filename
        if not local_path.exists():
            local_path.write_bytes(image_data)
        url = f"{_get_local_fallback_url_prefix()}/{filename}"
        logger.info("OSS 降级：模特图已存本地: %s", url)
        return url

    async def close(self):
        """释放底层 httpx.AsyncClient 资源

        ModelService 是每任务一个实例（model_consumer.py），
        必须在任务结束后调用 close() 释放 VtonClient 持有的 httpx.AsyncClient。
        """
        if self._vton_client is not None:
            try:
                await self._vton_client.close()
            except Exception as e:
                logger.warning("关闭 VtonClient 异常: %s", e)
            self._vton_client = None


# 品类中→英文件名映射（避免中文文件名在 nginx/OSS 编码问题）
_CATEGORY_FILENAME_MAP = {
    "上衣": "tops",
    "下装": "bottoms",
    "全身套装": "dress",
    "帽子": "hat",
    "鞋": "shoes",
    "包": "bag",
    "配饰": "accessory",
}


def _category_to_filename_safe(category: str) -> str:
    """品类中文转英文文件名安全字符串"""
    return _CATEGORY_FILENAME_MAP.get(category, "item")

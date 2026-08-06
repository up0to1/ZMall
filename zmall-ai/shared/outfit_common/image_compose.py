"""AI 随心搭·换装图 PIL 多件合成（§3.12）

ai-models 商品驱动模式和 ai-outfit 风格驱动模式共用此实现。
简单版策略（无姿态识别）：辅助品类商品图按经验区域贴到 base 图上。
"""
import io
import logging

logger = logging.getLogger(__name__)

# PIL 可选导入：未安装时降级为仅 VTON 主图（与 ai-outfit 节点4 历史行为一致）
try:
    from PIL import Image
    _PIL_AVAILABLE = True
except ImportError:
    Image = None  # type: ignore
    _PIL_AVAILABLE = False

# 辅助品类的 PIL 贴图区域（按 base 图比例，0~1）
# 设计文档 §3.12 ㉘：下装→腰部以下；鞋→脚部；帽子→头部上方
# P1 简单版无姿态识别，按经验区域贴图
AUX_CATEGORY_REGION: dict[str, tuple[float, float, float, float]] = {
    # category_cn: (x_ratio_start, y_ratio_start, x_ratio_end, y_ratio_end)
    "下装": (0.10, 0.45, 0.90, 0.78),   # 腰部以下
    "鞋":   (0.15, 0.85, 0.85, 1.00),   # 脚部
    "帽子": (0.20, 0.00, 0.80, 0.18),   # 头部上方
    "包":   (0.65, 0.45, 1.00, 0.78),   # 右侧腰下
    "配饰": (0.00, 0.45, 0.35, 0.78),   # 左侧腰下
}


def compose_full_outfit_image(
    base_image_bytes: bytes,
    aux_items: list[dict],
    log_prefix: str = "outfit",
) -> bytes | None:
    """PIL 贴图合成：在 base 图上叠加辅助品类商品图（§3.12）

    简单版策略（无姿态识别）：
    - 下装贴在腰部以下，鞋贴在脚部，帽子贴在头部上方，包/配饰贴在侧边
    - 商品图按目标区域等比缩放后居中粘贴（contain 模式，不拉伸变形）
    - 商品图本身通常是白底/纯色背景，直接 paste 即可（避免 alpha 合成复杂度）

    Args:
        base_image_bytes: base 图二进制（VTON 结果或主商品图）
        aux_items: 辅助品类商品列表 [{category, image_bytes}, ...]
        log_prefix: 调用方日志前缀（如 "[节点4]" / "[商品驱动]"），便于定位
    Returns:
        合成后的 JPEG 二进制；PIL 不可用或合成失败返回 None，调用方降级用 base 图
    """
    if not _PIL_AVAILABLE:
        logger.warning("%s PIL 不可用，跳过全件合成（仅返回 base 图）", log_prefix)
        return None
    if not aux_items:
        return None

    try:
        base = Image.open(io.BytesIO(base_image_bytes)).convert("RGB")
        base_w, base_h = base.size

        for it in aux_items:
            category = it.get("category")
            img_bytes = it.get("image_bytes")
            if not img_bytes or category not in AUX_CATEGORY_REGION:
                continue
            try:
                aux = Image.open(io.BytesIO(img_bytes)).convert("RGB")
            except Exception as e:
                logger.warning("%s 辅助商品图打开失败（category=%s）: %s",
                               log_prefix, category, e)
                continue

            # 计算目标区域
            x0_r, y0_r, x1_r, y1_r = AUX_CATEGORY_REGION[category]
            target_x = int(base_w * x0_r)
            target_y = int(base_h * y0_r)
            target_w = max(1, int(base_w * (x1_r - x0_r)))
            target_h = max(1, int(base_h * (y1_r - y0_r)))

            # 等比缩放 aux 至目标区域内（contain 模式，不拉伸变形）
            aux_w, aux_h = aux.size
            scale = min(target_w / aux_w, target_h / aux_h)
            new_w = max(1, int(aux_w * scale))
            new_h = max(1, int(aux_h * scale))
            aux_resized = aux.resize((new_w, new_h), Image.Resampling.LANCZOS)

            # 在目标区域内居中粘贴
            paste_x = target_x + (target_w - new_w) // 2
            paste_y = target_y + (target_h - new_h) // 2
            base.paste(aux_resized, (paste_x, paste_y))

        # 输出 JPEG 二进制
        out_buf = io.BytesIO()
        base.save(out_buf, format="JPEG", quality=90)
        return out_buf.getvalue()
    except Exception as e:
        logger.warning("%s PIL 全件合成失败（降级仅用 base 图）: %s", log_prefix, e)
        return None

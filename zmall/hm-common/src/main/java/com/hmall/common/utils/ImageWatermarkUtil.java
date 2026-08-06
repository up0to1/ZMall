package com.hmall.common.utils;

import lombok.extern.slf4j.Slf4j;

import javax.imageio.ImageIO;
import java.awt.AlphaComposite;
import java.awt.Color;
import java.awt.Font;
import java.awt.FontMetrics;
import java.awt.Graphics2D;
import java.awt.image.BufferedImage;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;

/**
 * 图片水印工具类
 *
 * <p>2026-07-19 新增：用于 AI 模特图上传时给图片右下角加商家店铺名水印（防滥用）。
 *
 * <p>设计：
 * <ul>
 *   <li>支持 jpg/jpeg/png/webp/gif（gif 仅取首帧）</li>
 *   <li>水印位置：右下角，距边缘 10px 内边距</li>
 *   <li>水印样式：白色文字 + 50% 透明度 + 黑色阴影，字体大小按图片宽度自适应（width/25）</li>
 *   <li>输出格式：原格式优先；不可识别时输出 jpg（压缩率更高，OSS 存储更省）</li>
 * </ul>
 *
 * <p>失败容忍：水印生成异常时返回原图 bytes，不阻塞上传主流程（仅记录日志）。
 */
@Slf4j
public class ImageWatermarkUtil {

    /** 水印距右下角的内边距（px） */
    private static final int PADDING = 10;
    /** 水印透明度（0.0~1.0，0.5=半透明） */
    private static final float ALPHA = 0.5f;
    /** 字体大小自适应比例（图片宽度 / 此值 = 字体大小） */
    private static final int FONT_SIZE_DIVISOR = 25;
    /** 最小字体大小（避免小图字体过小看不清） */
    private static final int MIN_FONT_SIZE = 14;

    private ImageWatermarkUtil() {
    }

    /**
     * 给图片右下角加水印文字（店铺名）。
     *
     * @param imageBytes  原图二进制
     * @param watermarkText 水印文本（如店铺名）；为空时直接返回原图
     * @param formatName  图片格式名（jpg/jpeg/png/gif/webp），null 时自动探测
     * @return 加水印后的图片二进制；水印失败时返回原图 bytes
     */
    public static byte[] addTextWatermark(byte[] imageBytes, String watermarkText, String formatName) {
        if (imageBytes == null || imageBytes.length == 0) {
            return imageBytes;
        }
        if (watermarkText == null || watermarkText.isBlank()) {
            return imageBytes;
        }
        try {
            BufferedImage original = readImage(imageBytes);
            if (original == null) {
                log.warn("水印工具：图片解码失败，跳过水印: size={}", imageBytes.length);
                return imageBytes;
            }
            String outputFormat = resolveFormat(formatName, imageBytes);
            BufferedImage watermarked = drawWatermark(original, watermarkText);
            ByteArrayOutputStream baos = new ByteArrayOutputStream(imageBytes.length + 4096);
            if (!ImageIO.write(watermarked, outputFormat, baos)) {
                log.warn("水印工具：ImageIO.write 返回 false（无合适 writer），返回原图: format={}", outputFormat);
                return imageBytes;
            }
            return baos.toByteArray();
        } catch (Exception e) {
            log.warn("水印工具：加水印异常，返回原图: {}", e.getMessage());
            return imageBytes;
        }
    }

    /**
     * 从 MultipartFile 内容类型推断图片格式名
     *
     * @param contentType 如 "image/jpeg"、"image/png"
     * @return "jpg"/"png"/"gif"/"webp"，无法识别返回 "jpg"
     */
    public static String inferFormatFromContentType(String contentType) {
        if (contentType == null) {
            return "jpg";
        }
        String ct = contentType.toLowerCase();
        if (ct.contains("png")) return "png";
        if (ct.contains("gif")) return "gif";
        if (ct.contains("webp")) return "webp";
        return "jpg"; // jpeg 兼容
    }

    private static BufferedImage readImage(byte[] bytes) throws IOException {
        try (InputStream is = new ByteArrayInputStream(bytes)) {
            BufferedImage img = ImageIO.read(is);
            if (img == null) {
                return null;
            }
            // gif/webp 在 Java 标准库下可能读不到，由调用方 fallback
            return img;
        }
    }

    private static BufferedImage drawWatermark(BufferedImage original, String text) {
        int w = original.getWidth();
        int h = original.getHeight();
        // 输出统一用 ARGB 避免 jpg 不支持 alpha 通道导致背景变黑
        BufferedImage result = new BufferedImage(w, h, BufferedImage.TYPE_INT_RGB);
        Graphics2D g = result.createGraphics();
        try {
            // 先画原图
            g.drawImage(original, 0, 0, null);
            // 字体大小自适应（最小 14px）
            int fontSize = Math.max(MIN_FONT_SIZE, w / FONT_SIZE_DIVISOR);
            Font font = new Font(Font.SANS_SERIF, Font.BOLD, fontSize);
            g.setFont(font);
            g.setComposite(AlphaComposite.getInstance(AlphaComposite.SRC_OVER, ALPHA));
            FontMetrics fm = g.getFontMetrics();
            int textWidth = fm.stringWidth(text);
            int textHeight = fm.getAscent();
            // 右下角位置（距边缘 PADDING）
            int x = w - textWidth - PADDING;
            int y = h - PADDING;
            // 阴影（黑色，提升浅色背景下的可读性）
            g.setColor(Color.BLACK);
            g.drawString(text, x + 1, y + 1);
            // 主文字（白色）
            g.setColor(Color.WHITE);
            g.drawString(text, x, y);
        } finally {
            g.dispose();
        }
        return result;
    }

    private static String resolveFormat(String formatName, byte[] imageBytes) {
        if (formatName != null && !formatName.isBlank()) {
            String f = formatName.toLowerCase();
            if (f.contains("jpeg")) return "jpg";
            if (f.contains("jpg")) return "jpg";
            if (f.contains("png")) return "png";
            if (f.contains("gif")) return "gif";
            if (f.contains("webp")) return "webp";
        }
        // 默认 jpg（兼容性最好，体积小）
        return "jpg";
    }
}

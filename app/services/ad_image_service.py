"""Local advertisement image generation with static PNG and animated GIF output."""

from __future__ import annotations

import io
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import AdImageConfig
from app.models import SystemSetting

AD_IMAGE_SETTINGS_KEY = "ad_image_defaults"


class AdImageError(ValueError):
    """Raised when advertisement image parameters are invalid."""


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        Path(r"C:\Windows\Fonts\msyh.ttc"),
        Path(r"C:\Windows\Fonts\arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def _cover(image: Image.Image, width: int, height: int) -> Image.Image:
    return ImageOps.fit(image.convert("RGB"), (width, height), method=Image.Resampling.LANCZOS)


def _gradient(width: int, height: int) -> Image.Image:
    image = Image.new("RGB", (width, height), "#172554")
    draw = ImageDraw.Draw(image)
    for y in range(height):
        ratio = y / max(height - 1, 1)
        color = (
            int(23 + (88 - 23) * ratio),
            int(37 + (28 - 37) * ratio),
            int(84 + (135 - 84) * ratio),
        )
        draw.line((0, y, width, y), fill=color)
    return image


def _wrap_text(text: str, font: ImageFont.ImageFont, max_width: int) -> str:
    lines: list[str] = []
    for paragraph in text.splitlines() or [""]:
        current = ""
        for char in paragraph:
            candidate = current + char
            if current and font.getlength(candidate) > max_width:
                lines.append(current)
                current = char
            else:
                current = candidate
        lines.append(current)
    return "\n".join(lines)


def _compose_frame(
    text: str,
    width: int,
    height: int,
    background: Image.Image | None,
    *,
    offset: int = 0,
    brightness: float = 1.0,
) -> Image.Image:
    if background is None:
        canvas = _gradient(width, height)
    else:
        canvas = _cover(background, width, height)

    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 105))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay)
    if brightness != 1.0:
        canvas = ImageEnhance.Brightness(canvas.convert("RGB")).enhance(brightness).convert("RGBA")

    if text:
        font = _font(max(28, int(min(width, height) * 0.075)))
        margin = int(width * 0.1)
        wrapped = _wrap_text(text, font, width - margin * 2)
        bbox = ImageDraw.Draw(canvas).multiline_textbbox((0, 0), wrapped, font=font, spacing=18)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        x = (width - text_width) / 2
        y = (height - text_height) / 2 + offset
        draw = ImageDraw.Draw(canvas)
        draw.multiline_text(
            (x + 3, y + 3),
            wrapped,
            font=font,
            fill=(0, 0, 0, 180),
            align="center",
            spacing=18,
        )
        draw.multiline_text(
            (x, y),
            wrapped,
            font=font,
            fill="white",
            align="center",
            spacing=18,
        )
    return canvas.convert("RGB")


def generate_static_ad(
    text: str,
    width: int,
    height: int,
    background_bytes: bytes | None = None,
) -> bytes:
    if not text.strip():
        raise AdImageError("广告文字不能为空。")
    if not 256 <= width <= 4096 or not 256 <= height <= 4096:
        raise AdImageError("图片尺寸必须在 256 到 4096 像素之间。")
    background = Image.open(io.BytesIO(background_bytes)) if background_bytes else None
    frame = _compose_frame(text.strip(), width, height, background)
    output = io.BytesIO()
    frame.save(output, format="PNG", optimize=True)
    return output.getvalue()


def generate_dynamic_ad(
    text: str,
    width: int,
    height: int,
    background_bytes: bytes | None = None,
) -> bytes:
    if not text.strip():
        raise AdImageError("广告文字不能为空。")
    if not 256 <= width <= 4096 or not 256 <= height <= 4096:
        raise AdImageError("图片尺寸必须在 256 到 4096 像素之间。")
    background = Image.open(io.BytesIO(background_bytes)) if background_bytes else None
    frames: list[Image.Image] = []
    total = 12
    for index in range(total):
        offset = int(8 * ((index / (total - 1)) * 2 - 1))
        brightness = 0.88 + 0.12 * (1 - abs(index - total / 2) / (total / 2))
        frames.append(
            _compose_frame(
                text.strip(),
                width,
                height,
                background,
                offset=offset,
                brightness=brightness,
            )
        )
    output = io.BytesIO()
    frames[0].save(
        output,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=140,
        loop=0,
        optimize=True,
    )
    return output.getvalue()


async def get_ad_image_defaults(
    session: AsyncSession,
    defaults: AdImageConfig,
) -> AdImageConfig:
    row = await session.get(SystemSetting, AD_IMAGE_SETTINGS_KEY)
    if row is None:
        return defaults
    try:
        data = json.loads(row.value)
    except (TypeError, json.JSONDecodeError):
        return defaults
    merged = defaults.model_dump()
    if isinstance(data, dict):
        merged.update(data)
    try:
        return AdImageConfig.model_validate(merged)
    except ValueError:
        return defaults


async def set_ad_image_defaults(
    session: AsyncSession,
    settings: AdImageConfig,
) -> AdImageConfig:
    encoded = json.dumps(settings.model_dump(), ensure_ascii=False)
    row = await session.get(SystemSetting, AD_IMAGE_SETTINGS_KEY)
    if row is None:
        session.add(SystemSetting(key=AD_IMAGE_SETTINGS_KEY, value=encoded))
    else:
        row.value = encoded
    await session.commit()
    return settings

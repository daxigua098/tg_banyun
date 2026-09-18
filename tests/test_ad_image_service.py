from __future__ import annotations

from io import BytesIO

from PIL import Image

from app.services.ad_image_service import generate_dynamic_ad, generate_static_ad


def test_generate_static_ad_image() -> None:
    content = generate_static_ad('测试广告', 512, 512)
    image = Image.open(BytesIO(content))
    assert image.format == 'PNG'
    assert image.size == (512, 512)


def test_generate_dynamic_ad_image() -> None:
    content = generate_dynamic_ad('测试动态广告', 320, 320)
    image = Image.open(BytesIO(content))
    assert image.format == 'GIF'
    assert image.size == (320, 320)
    assert image.is_animated

"""生成插件 logo.png（256x256，二次元粉色风格）。"""

from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

BASE = Path(__file__).resolve().parent
PLUGIN_DIR = (
    BASE.parent if (BASE.parent / "main.py").is_file() else BASE.parent / "astrbot_plugin_yc_stats"
)

OUT = PLUGIN_DIR / "logo.png"
SIZE = 256


def load_font(size: int) -> ImageFont.FreeTypeFont:
    """加载一个中文字体用于绘制小字。

    Args:
        size: 字号。

    Returns:
        字体对象。
    """
    for candidate in (
        "C:/Windows/Fonts/msyhbd.ttc",
        "C:/Windows/Fonts/msyh.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    ):
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def main() -> None:
    """绘制并保存 logo。"""
    canvas = Image.new("RGBA", (SIZE, SIZE), (255, 246, 251, 255))
    draw = ImageDraw.Draw(canvas)
    # 竖向渐变背景
    for y in range(SIZE):
        ratio = y / (SIZE - 1)
        draw.line(
            [(0, y), (SIZE, y)],
            fill=(
                int(255 - 8 * ratio),
                int(236 + 12 * ratio),
                int(248 + 7 * ratio),
                255,
            ),
        )

    # 柔光色块
    blobs = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    blob_draw = ImageDraw.Draw(blobs)
    blob_draw.ellipse([-60, -70, 120, 110], fill=(255, 205, 232, 200))
    blob_draw.ellipse([140, 120, 320, 300], fill=(206, 224, 255, 190))
    canvas = Image.alpha_composite(canvas, blobs.filter(ImageFilter.GaussianBlur(18)))

    draw = ImageDraw.Draw(canvas)
    # 磁力马蹄形磁铁：顶部圆弧 + 两条腿 + 两端彩色磁极
    magnet_bbox = [70, 62, 186, 178]
    pole_pink = (255, 122, 180, 255)
    pole_violet = (150, 132, 255, 255)

    # 柔和投影
    shadow = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.arc(magnet_bbox, start=180, end=360, fill=(198, 148, 190, 180), width=34)
    shadow_draw.rounded_rectangle([64, 108, 96, 188], radius=16, fill=(198, 148, 190, 180))
    shadow_draw.rounded_rectangle([160, 108, 192, 188], radius=16, fill=(198, 148, 190, 180))
    canvas = Image.alpha_composite(canvas, shadow.filter(ImageFilter.GaussianBlur(9)))

    draw = ImageDraw.Draw(canvas)
    draw.arc(magnet_bbox, start=180, end=360, fill=(255, 255, 255, 255), width=32)
    draw.rounded_rectangle([69, 110, 101, 186], radius=16, fill=(255, 255, 255, 255))
    draw.rounded_rectangle([155, 110, 187, 186], radius=16, fill=(255, 255, 255, 255))
    # 磁极
    draw.rounded_rectangle([70, 156, 100, 186], radius=14, fill=pole_pink)
    draw.rounded_rectangle([156, 156, 186, 186], radius=14, fill=pole_violet)
    # 高光
    draw.arc([80, 74, 176, 170], start=196, end=250, fill=(255, 255, 255, 235), width=7)

    # 樱花花瓣装饰
    rng = random.Random(7)
    for _ in range(9):
        size = rng.randint(14, 26)
        petal = Image.new("RGBA", (size * 2, size * 2), (0, 0, 0, 0))
        petal_draw = ImageDraw.Draw(petal)
        petal_draw.ellipse(
            [0, 0, size * 2, int(size * 1.2)],
            fill=(255, rng.randint(170, 205), rng.randint(205, 230), 190),
        )
        petal = petal.rotate(rng.randint(0, 359), expand=True, resample=Image.BICUBIC)
        x = rng.choice([rng.randint(0, 70), rng.randint(160, 220)])
        y = rng.choice([rng.randint(0, 60), rng.randint(170, 225)])
        canvas.alpha_composite(petal, (x, y))

    # 底部小字标签
    draw = ImageDraw.Draw(canvas)
    font = load_font(30)
    text = "验车"
    text_width = draw.textlength(text, font=font)
    draw.rounded_rectangle(
        [(SIZE - text_width) / 2 - 14, 190, (SIZE + text_width) / 2 + 14, 232],
        radius=16,
        fill=(255, 255, 255, 235),
    )
    draw.text(((SIZE - text_width) / 2, 196), text, font=font, fill=(206, 88, 152))

    canvas.convert("RGB").save(OUT, "PNG")
    print(f"logo written: {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()

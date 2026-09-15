"""把工作目录里的「鲸鱼娘.png」处理成插件资源背景图。

输出：astrbot_plugin_yc_stats/resources/background.jpg（1920x1080，JPEG）
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

BASE = Path(__file__).resolve().parent
PLUGIN_DIR = (
    BASE.parent if (BASE.parent / "main.py").is_file() else BASE.parent / "astrbot_plugin_yc_stats"
)
# 源图优先取仓库根目录/工作区根目录下的素材图
SOURCE_CANDIDATES = (
    BASE.parent / "鲸鱼娘.png",
    BASE.parent.parent / "鲸鱼娘.png",
    PLUGIN_DIR / "resources" / "background-source.png",
)


def find_source() -> Path | None:
    """查找背景素材源图。

    Returns:
        找到的源图路径；都没有时返回 ``None``。
    """
    for candidate in SOURCE_CANDIDATES:
        if candidate.is_file():
            return candidate
    return None

DST = PLUGIN_DIR / "resources" / "background.jpg"


def main() -> None:
    """缩放并压缩背景图，另存为插件内置资源。"""
    source = find_source()
    if source is None:
        raise SystemExit(
            "找不到背景素材图，请把原图放到以下任一位置后重试：\n"
            + "\n".join(f"  - {item}" for item in SOURCE_CANDIDATES)
        )
    SRC = source
    DST.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(SRC) as img:
        img = img.convert("RGB")
        print(f"源图: {img.width}x{img.height}")
        target = (1920, 1080)
        # 16:9 原图直接缩放；非 16:9 则居中裁切后再缩放
        ratio = max(target[0] / img.width, target[1] / img.height)
        resized = img.resize(
            (round(img.width * ratio), round(img.height * ratio)), Image.LANCZOS
        )
        left = (resized.width - target[0]) // 2
        top = (resized.height - target[1]) // 2
        resized = resized.crop((left, top, left + target[0], top + target[1]))
        resized.save(DST, "JPEG", quality=88, optimize=True, progressive=True)
    print(f"已生成: {DST} ({DST.stat().st_size/1024:.0f} KB, {target[0]}x{target[1]})")


if __name__ == "__main__":
    main()

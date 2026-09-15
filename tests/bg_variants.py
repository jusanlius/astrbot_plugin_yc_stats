"""背景图毛玻璃参数对比：生成不同 blur/dim 组合的战报图，便于挑选默认值。

运行后会输出 tests/out/variants/variant-<blur>-<dim>.jpg
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path

BASE = Path(__file__).resolve().parent
PLUGIN_DIR = (
    BASE.parent if (BASE.parent / "main.py").is_file() else BASE.parent / "astrbot_plugin_yc_stats"
)

sys.path.insert(0, str(BASE))
import test_yc_stats as harness  # noqa: E402  （复用桩模块与插件加载逻辑）

OUT = BASE / "out" / "variants"
OUT.mkdir(parents=True, exist_ok=True)

VARIANTS = [
    (4, 8),
    (5, 12),
    (6, 20),
    (8, 20),
    (6, 35),
]


async def main() -> None:
    """按不同参数逐个渲染同一份战报数据。"""
    module = harness.load_plugin_module()
    report = {
        "title": "今日验车战报",
        "date": "2026-09-15",
        "group_id": "123456",
        "group_name": "验车交流群",
        "total_count": 27,
        "unique_count": 9,
        "user_count": 6,
        "shown_count": 3,
        "more_count": 0,
        "generated_at": "2026-09-20 23:00",
        "rows": [
            {"rank": 1, "name": "【自压】某热门动画合集 1080P", "count": 8, "pct": 100, "cls": "r1", "link": ""},
            {"rank": 2, "name": "4K 修复版电影资源包", "count": 5, "pct": 62, "cls": "r2", "link": ""},
            {"rank": 3, "name": "电视剧全集整合（中字）", "count": 3, "pct": 38, "cls": "r3", "link": ""},
        ],
    }
    for blur, dim in VARIANTS:
        plugin, _, _ = harness.make_plugin(
            module, background_blur=blur, background_dim=dim
        )
        path = await asyncio.to_thread(plugin._render_report_pillow, report)
        target = OUT / f"variant-b{blur}-d{dim}.jpg"
        target.write_bytes(path.read_bytes())
        print(f"blur={blur:<3} dim={dim:<3} -> {target.name}")


if __name__ == "__main__":
    asyncio.run(main())

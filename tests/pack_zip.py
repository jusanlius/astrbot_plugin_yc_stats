"""打包插件 zip（排除 .git / 缓存 / 测试产物 / 本地 zip），用于手动安装或发布。

用法：python tests/pack_zip.py [输出路径]
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

BASE = Path(__file__).resolve().parent
PLUGIN_DIR = (
    BASE.parent if (BASE.parent / "main.py").is_file() else BASE.parent / "astrbot_plugin_yc_stats"
)
DEFAULT_OUT = PLUGIN_DIR.parent / f"{PLUGIN_DIR.name}.zip"

EXCLUDE_DIRS = {"__pycache__", ".git", ".pytest_cache", ".ruff_cache", ".vscode", ".idea", "out"}
EXCLUDE_SUFFIX = {".pyc", ".pyo", ".zip", ".log"}


def main() -> None:
    """打包插件目录。

    Raises:
        SystemExit: 缺少 main.py 时。
    """
    if not (PLUGIN_DIR / "main.py").is_file():
        raise SystemExit(f"没找到插件入口: {PLUGIN_DIR / 'main.py'}")
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    count = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(PLUGIN_DIR.rglob("*")):
            if any(part in EXCLUDE_DIRS for part in path.parts):
                continue
            if not path.is_file() or path.suffix.lower() in EXCLUDE_SUFFIX:
                continue
            zf.write(path, Path(PLUGIN_DIR.name) / path.relative_to(PLUGIN_DIR))
            count += 1
    size_kb = out.stat().st_size / 1024
    print(f"打包完成: {out}")
    print(f"文件数: {count} | 体积: {size_kb:.0f} KB（市场限制 16384 KB）")


if __name__ == "__main__":
    main()

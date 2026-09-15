"""生成插件 Pages 的本地预览：把页面复制到 tests/out/page 并注入 mock bridge。

用于在没有 AstrBot 的环境下，用浏览器检查白名单页面的 UI。
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
PLUGIN_DIR = (
    BASE.parent if (BASE.parent / "main.py").is_file() else BASE.parent / "astrbot_plugin_yc_stats"
)

OUT = BASE / "out" / "page"
SRC = PLUGIN_DIR / "pages" / "whitelist"

OVERVIEW = {
    "plugin": "astrbot_plugin_yc_stats",
    "today": "2026-09-20",
    "whitelist": ["123456"],
    "groups": [
        {"group_id": "123456", "group_name": "验车交流群", "source": "live", "whitelisted": True,
         "today_total": 27, "today_unique": 9},
        {"group_id": "654321", "group_name": "资源分享②群", "source": "live", "whitelisted": False,
         "today_total": 12, "today_unique": 5},
        {"group_id": "888888", "group_name": "测试群", "source": "record", "whitelisted": False,
         "today_total": 3, "today_unique": 2},
        {"group_id": "999999", "group_name": "", "source": "manual", "whitelisted": True,
         "today_total": 0, "today_unique": 0},
    ],
    "days": ["2026-09-20", "2026-09-19", "2026-09-18"],
    "settings": {
        "enabled": True,
        "today_command": True,
        "reply_receipt": False,
        "block_llm_reply": True,
        "push_enabled": True,
        "push_time": "23:00",
        "push_top_n": 15,
        "push_min_count": 1,
        "push_empty_report": False,
        "name_max_len": 20,
        "render_mode": "auto",
        "image_title": "今日验车战报",
        "background_enabled": True,
        "background_blur": 6,
        "background_dim": 14,
        "background_path": "",
        "background_source": "data/plugin_data/astrbot_plugin_yc_stats/background.jpg",
        "triggers": ["#验车", "验车"],
        "retention_days": 60,
    },
    "last_push_day": "2026-09-19",
    "pushes": {"123456": 1758380400},
    "stats_total_days": 12,
    "data_dir": "data/plugin_data/astrbot_plugin_yc_stats",
}

STATS = {
    "date": "2026-09-20",
    "group_id": "123456",
    "entries": [
        {"key": "hash:1", "group_id": "123456", "group_name": "验车交流群",
         "name": "【自压】某热门动画合集 1080P", "link": "magnet:?xt=urn:btih:1", "count": 8,
         "user_count": 4},
        {"key": "hash:2", "group_id": "123456", "group_name": "验车交流群",
         "name": "4K 修复版电影资源包", "link": "magnet:?xt=urn:btih:2", "count": 5, "user_count": 3},
        {"key": "hash:3", "group_id": "123456", "group_name": "验车交流群",
         "name": "电视剧全集整合（中字）", "link": "magnet:?xt=urn:btih:3", "count": 3, "user_count": 2},
    ],
}

MOCK_BRIDGE = """
window.AstrBotPluginPage = {
  async ready() {
    return { pluginName: "astrbot_plugin_yc_stats", pageName: "whitelist",
             pageTitle: "验车记录 · 群白名单", locale: "zh-CN", isDark: false, i18n: {} };
  },
  getContext() { return { isDark: false }; },
  getLocale() { return "zh-CN"; },
  t(key, fallback) { return fallback; },
  onContext() { return () => {}; },
  async apiGet(endpoint) {
    if (endpoint === "overview") return __OVERVIEW__;
    if (endpoint === "stats") return __STATS__;
    if (endpoint === "background") return __BACKGROUND__;
    throw new Error("unknown endpoint " + endpoint);
  },
  async apiPost(endpoint, body) {
    if (endpoint === "settings") return { saved: body };
    if (endpoint === "whitelist") return { whitelist: body.groups };
    if (endpoint === "preview") return { image: "__IMAGE__", date: body.date, total_count: 16, unique_count: 3 };
    if (endpoint === "push") return { results: [{ group_id: "123456", ok: true, error: "" }] };
    throw new Error("unknown endpoint " + endpoint);
  },
};
"""


def build_background_uri() -> str:
    """把插件内置背景图压到 1280 宽并编码成 data URI（与插件运行时一致）。

    Returns:
        ``data:image/jpeg;base64,...``；图片缺失时返回空串。
    """
    import base64
    from io import BytesIO

    from PIL import Image

    source = PLUGIN_DIR / "resources" / "background.jpg"
    if not source.is_file():
        return ""
    with Image.open(source) as img:
        img = img.convert("RGB")
        if img.width > 1280:
            height = round(img.height * 1280 / img.width)
            img = img.resize((1280, height), Image.LANCZOS)
        buf = BytesIO()
        img.save(buf, "JPEG", quality=78, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def main() -> None:
    """复制页面并注入 mock bridge。"""
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    for item in SRC.iterdir():
        if item.is_file():
            shutil.copy2(item, OUT / item.name)
    html = (OUT / "index.html").read_text(encoding="utf-8")
    dark = "true" if "--dark" in sys.argv else "false"
    background = {
        "enabled": True,
        "image": build_background_uri(),
        "blur": 6,
        "dim": 14,
        "source": "astrbot_plugin_yc_stats/resources/background.jpg",
        "focal_x": 0.32,
    }
    mock = (
        MOCK_BRIDGE.replace("__OVERVIEW__", json.dumps(OVERVIEW, ensure_ascii=False))
        .replace("__STATS__", json.dumps(STATS, ensure_ascii=False))
        .replace("__BACKGROUND__", json.dumps(background, ensure_ascii=False))
        .replace("__IMAGE__", "../preview-pillow.jpg")
        .replace("__DARK__", dark)
    )
    html = html.replace(
        '<script type="module" src="./app.js"></script>',
        f'<script>{mock}</script>\n  <script type="module" src="./app.js"></script>',
    )
    if dark == "true":
        html = html.replace('<html lang="zh-CN">', '<html lang="zh-CN" data-theme="dark">')
    (OUT / "index.html").write_text(html, encoding="utf-8")
    print(f"page preview written: {OUT / 'index.html'}")


if __name__ == "__main__":
    main()


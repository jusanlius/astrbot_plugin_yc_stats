"""验车记录统计插件 (astrbot_plugin_yc_stats).

功能概览:
    1. 记录群内 ``#验车 <磁力链接/名称>`` 指令后面的磁力名称，只保留前 N 个字（默认 20）。
    2. 按「群 + 日期 + 链接」维度统计同一个磁力链接当天被发送了几次。
    3. 每天 23:00（可配置）自动把当天战报渲染成二次元风格图片推送到群。
    4. WebUI 提供插件 Pages 页面，可视化维护群白名单 / 推送时间 / 立即推送。

指令:
    ``#验车 <磁力链接>``  记录一次（同一链接同一天重复发送会累加次数）
    ``#验车榜``          立即查看当前群当天的战报图
    ``#验车推送``        群管理员手动触发一次推送（用于补发/测试）

存储:
    数据保存在 ``data/plugin_data/astrbot_plugin_yc_stats/records.json``，
    图片保存在 ``data/plugin_data/astrbot_plugin_yc_stats/images/``。
    插件目录不写入任何运行期数据，重装/升级插件不会丢数据。
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import html as html_lib
import json
import random
import re
import time
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.message_components import Image, Plain
from astrbot.api.star import Context, Star
from astrbot.api.web import error_response, json_response, request
from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path

PLUGIN_NAME = "astrbot_plugin_yc_stats"
"""插件名，同时用作 Web API 路由前缀与数据目录名。"""

STORE_VERSION = 1
"""存储结构版本号，便于后续无损升级。"""

PLUGIN_DIR = Path(__file__).resolve().parent
"""插件目录，用于定位随插件分发的静态资源（如内置背景图）。"""

BACKGROUND_FILENAMES = (
    "background.jpg",
    "background.jpeg",
    "background.png",
    "background.webp",
    "bg.jpg",
    "bg.png",
    "bg.webp",
)
"""背景图候选文件名：先查插件数据目录，再查插件自带 resources/ 目录。"""

BACKGROUND_FOCAL_X = 0.32
"""背景图裁切焦点（0-1，横向）。鲸鱼娘位于画面偏左，竖版战报按此焦点裁切。"""

BACKGROUND_EMBED_WIDTH = 1280
"""嵌入 HTML 模板时背景图的最大宽度（文转图走网络请求，需控制 base64 体积）。"""

DEFAULT_TRIGGERS = ("#验车", "验车")
DEFAULT_PUSH_TIME = "23:00"
DEFAULT_NAME_MAX_LEN = 20
DEFAULT_BACKGROUND_BLUR = 6
DEFAULT_BACKGROUND_DIM = 14

MAGNET_RE = re.compile(r"magnet:\?[^\s\u3000<>\"'）】]+", re.IGNORECASE)
BTIH_RE = re.compile(r"urn:btih:([0-9a-zA-Z]{32,40})", re.IGNORECASE)
HEX40_RE = re.compile(r"(?<![0-9a-zA-Z])([0-9a-fA-F]{40})(?![0-9a-zA-Z])")
AT_PREFIX_RE = re.compile(r"^(?:\[At:\d+\]\s*|@[^\s\u3000]+\s+)+")
TRIM_CHARS = " \u3000\t:：-—–|/,，。.、;；"

PREVIEW_WORDS = ("榜", "榜单", "报表", "战报", "统计", "排行", "排行榜")
PUSH_WORDS = ("推送", "立即推送", "马上推送")

ANIME_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  html, body { background: #fdf2f8; }
  body {
    width: 720px;
    font-family: "Noto Sans CJK SC", "Noto Sans SC", "Source Han Sans SC",
                 "Microsoft YaHei", "PingFang SC", "Hiragino Sans GB", sans-serif;
    color: #4a3b52;
  }
  .poster {
    position: relative;
    width: 720px;
    min-height: 420px;
    padding: 26px 26px 18px;
    overflow: hidden;
    background: linear-gradient(165deg, #fff7fb 0%, #fbe9ff 44%, #e9f3ff 100%);
  }
  /* 背景图：整层放大后做毛玻璃模糊，边缘由 .poster 的 overflow 裁掉 */
  .bg {
    position: absolute; inset: -30px;
    background-size: cover;
    background-position: 32% center;
    background-repeat: no-repeat;
    filter: blur({{ bg_blur }}px) saturate(1.06) brightness(1.02);
    transform: scale(1.06);
  }
  /* 磨砂白纱：轻雾化照片，保证文字可读又不糊掉底图 */
  .frost {
    position: absolute; inset: 0;
    background:
      radial-gradient(120% 70% at 50% 4%, rgba(255, 255, 255, .34) 0%, rgba(255, 255, 255, 0) 62%),
      linear-gradient(165deg, rgba(232, 242, 255, {{ bg_alpha }}) 0%, rgba(255, 255, 255, {{ bg_alpha }}) 44%, rgba(255, 232, 244, {{ bg_alpha }}) 100%);
  }
  /* 毛玻璃高光边 */
  .poster.has-bg::after {
    content: ""; position: absolute; inset: 10px; border-radius: 22px;
    border: 1px solid rgba(255, 255, 255, .5); pointer-events: none;
  }
  .blob { position: absolute; border-radius: 50%; opacity: .5; }
  .b1 { width: 260px; height: 260px; left: -70px; top: -80px; background: radial-gradient(circle, #ffd9ec 0%, rgba(255,217,236,0) 70%); }
  .b2 { width: 300px; height: 300px; right: -90px; top: 40px; background: radial-gradient(circle, #d9e6ff 0%, rgba(217,230,255,0) 70%); }
  .b3 { width: 240px; height: 240px; left: 40px; bottom: -110px; background: radial-gradient(circle, #ffe6f2 0%, rgba(255,230,242,0) 70%); }
  .petal { position: absolute; width: 22px; height: 22px; opacity: .75;
           border-radius: 72% 18% 72% 18%;
           background: linear-gradient(135deg, #ffd0e4, #ff9ec4); }
  .p1 { left: 34px; top: 96px; transform: rotate(18deg); }
  .p2 { left: 88px; top: 42px; transform: rotate(-32deg); width: 16px; height: 16px; opacity: .6; }
  .p3 { right: 46px; top: 128px; transform: rotate(42deg); width: 18px; height: 18px; opacity: .65; }
  .p4 { right: 120px; top: 30px; transform: rotate(-14deg); width: 14px; height: 14px; opacity: .5; }
  .p5 { left: 26px; bottom: 78px; transform: rotate(64deg); width: 16px; height: 16px; opacity: .55; }
  .p6 { right: 30px; bottom: 140px; transform: rotate(-48deg); width: 20px; height: 20px; opacity: .6; }
  .head { position: relative; text-align: center; padding: 6px 0 16px; }
  /* 有背景图时：标题区加一块毛玻璃面板，标题清晰可见，同时不遮挡照片主体 */
  .poster.has-bg .head {
    margin: 0 0 12px; padding: 14px 12px 14px;
    border-radius: 24px;
    background: rgba(255, 255, 255, .34);
    border: 1px solid rgba(255, 255, 255, .55);
    backdrop-filter: blur(10px) saturate(1.1);
    box-shadow: 0 8px 22px rgba(120, 110, 170, .12);
  }
  .tag {
    display: inline-block; padding: 3px 14px; border-radius: 999px;
    font-size: 12px; letter-spacing: 2px; color: #b3578a;
    background: rgba(255, 255, 255, .58); border: 1px solid rgba(255, 255, 255, .85);
    backdrop-filter: blur(14px) saturate(1.15);
  }
  h1 {
    margin: 10px 0 6px; font-size: 34px; letter-spacing: 2px;
    background: linear-gradient(90deg, #ff7fb6 0%, #b57bff 55%, #7fb6ff 100%);
    -webkit-background-clip: text; background-clip: text; color: #c96ba6;
  }
  .sub { font-size: 15px; color: #8b7c94; letter-spacing: 1px; }
  .stats { display: flex; gap: 12px; margin: 4px 0 16px; }
  .stat {
    flex: 1; padding: 12px 8px; border-radius: 18px; text-align: center;
    background: rgba(255, 255, 255, .60); border: 1px solid rgba(255, 255, 255, .88);
    box-shadow: 0 6px 16px rgba(150, 130, 190, .16);
    backdrop-filter: blur(16px) saturate(1.15);
  }
  .stat .num { font-size: 26px; font-weight: 700; color: #e0669f; }
  .stat .lab { margin-top: 2px; font-size: 12px; color: #8b7c94; }
  .list { display: flex; flex-direction: column; gap: 9px; }
  .row {
    display: flex; align-items: center; gap: 12px; padding: 9px 14px;
    border-radius: 16px; background: rgba(255, 255, 255, .58);
    border: 1px solid rgba(255, 255, 255, .88);
    box-shadow: 0 4px 12px rgba(150, 130, 190, .14);
    backdrop-filter: blur(16px) saturate(1.15);
  }
  .rank {
    width: 30px; height: 30px; flex: 0 0 30px; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    font-size: 15px; font-weight: 700; color: #fff; background: #c9b6d6;
  }
  .r1 .rank { background: linear-gradient(135deg, #ffc93c, #ff9f1c); }
  .r2 .rank { background: linear-gradient(135deg, #cfd8e3, #9fb0c4); }
  .r3 .rank { background: linear-gradient(135deg, #f4b183, #d98b5f); }
  .main { flex: 1; min-width: 0; }
  .name {
    font-size: 17px; line-height: 1.35; color: #4a3b52;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .bar { height: 6px; margin-top: 6px; border-radius: 999px; background: #f2e6f0; overflow: hidden; }
  .bar i { display: block; height: 100%; border-radius: 999px;
           background: linear-gradient(90deg, #ffa8cd, #b79bff); }
  .count {
    flex: 0 0 auto; padding: 5px 12px; border-radius: 999px; font-size: 16px; font-weight: 700;
    color: #fff; background: linear-gradient(135deg, #ff8fc0, #b07bff);
  }
  .more { margin-top: 10px; text-align: center; font-size: 13px; color: #9a8aa3; }
  .empty { padding: 34px 0 26px; text-align: center; }
  .face {
    position: relative; width: 132px; height: 118px; margin: 0 auto 14px;
    border-radius: 52% 52% 46% 46%; background: linear-gradient(160deg, #fff4fa, #ffe0ef);
    border: 2px solid #ffd0e4; box-shadow: 0 8px 20px rgba(232, 160, 200, .22);
  }
  .face .eye { position: absolute; top: 44px; width: 12px; height: 16px; border-radius: 50%;
               background: #6b5875; }
  .face .eye.l { left: 34px; }
  .face .eye.r { right: 34px; }
  .face .blush { position: absolute; top: 62px; width: 22px; height: 11px; border-radius: 50%;
                 background: #ffc3dd; opacity: .85; }
  .face .blush.l { left: 18px; }
  .face .blush.r { right: 18px; }
  .face .mouth { position: absolute; left: 50%; top: 68px; width: 14px; height: 8px;
                 margin-left: -7px; border-bottom: 3px solid #6b5875; border-radius: 0 0 12px 12px; }
  .face .ear { position: absolute; top: -14px; width: 34px; height: 34px;
               background: linear-gradient(135deg, #ffe3f1, #ffc2de);
               border: 2px solid #ffd0e4; }
  .face .ear.l { left: 8px; border-radius: 70% 20% 60% 30%; transform: rotate(-16deg); }
  .face .ear.r { right: 8px; border-radius: 20% 70% 30% 60%; transform: rotate(16deg); }
  .empty-title { font-size: 21px; color: #b3578a; }
  .empty-sub { margin-top: 6px; font-size: 14px; color: #9a8aa3; }
  footer {
    display: flex; justify-content: space-between; align-items: center;
    margin-top: 16px; padding-top: 12px; border-top: 1px dashed #f0d9e8;
    font-size: 12px; color: #9a8aa3;
  }
  /* 有背景图时：底部说明与「更多」提示加白晕，保证在照片上也看得清 */
  .poster.has-bg footer,
  .poster.has-bg .more,
  .poster.has-bg .sub,
  .poster.has-bg .empty-sub {
    color: #6d5b78;
    text-shadow: 0 1px 8px rgba(255, 255, 255, .95);
  }
  .poster.has-bg footer { border-top-color: rgba(255, 255, 255, .75); }
  .poster.has-bg .blob { opacity: .3; }
</style>
</head>
<body>
  <div class="poster{% if bg_uri %} has-bg{% endif %}">
    {% if bg_uri %}
    <div class="bg" style="background-image: url('{{ bg_uri }}')"></div>
    <div class="frost"></div>
    {% endif %}
    <div class="blob b1"></div>
    <div class="blob b2"></div>
    <div class="blob b3"></div>
    <div class="petal p1"></div>
    <div class="petal p2"></div>
    <div class="petal p3"></div>
    <div class="petal p4"></div>
    <div class="petal p5"></div>
    <div class="petal p6"></div>

    <div class="head">
      <div class="tag">DAILY REPORT</div>
      <h1>{{ title }}</h1>
      <div class="sub">{{ date }} · {{ group_name }}</div>
    </div>

    <div class="stats">
      <div class="stat"><div class="num">{{ total_count }}</div><div class="lab">总发送次数</div></div>
      <div class="stat"><div class="num">{{ unique_count }}</div><div class="lab">不同磁力</div></div>
      <div class="stat"><div class="num">{{ user_count }}</div><div class="lab">参与群友</div></div>
    </div>

    {% if rows %}
    <div class="list">
      {% for r in rows %}
      <div class="row {{ r.cls }}">
        <div class="rank">{{ r.rank }}</div>
        <div class="main">
          <div class="name">{{ r.name }}</div>
          <div class="bar"><i style="width: {{ r.pct }}%"></i></div>
        </div>
        <div class="count">×{{ r.count }}</div>
      </div>
      {% endfor %}
    </div>
    {% if more_count %}
    <div class="more">… 还有 {{ more_count }} 条记录未展示</div>
    {% endif %}
    {% else %}
    <div class="empty">
      <div class="face">
        <div class="ear l"></div><div class="ear r"></div>
        <div class="eye l"></div><div class="eye r"></div>
        <div class="blush l"></div><div class="blush r"></div>
        <div class="mouth"></div>
      </div>
      <div class="empty-title">今天还没有人验车哦</div>
      <div class="empty-sub">发送「#验车 磁力链接」即可上榜</div>
    </div>
    {% endif %}

    <footer>
      <span>{{ summary_line }}</span>
      <span>{{ generated_at }} 生成</span>
    </footer>
  </div>
</body>
</html>
"""


def _today_str() -> str:
    """返回本地日期字符串（YYYY-MM-DD）。"""
    return datetime.now().strftime("%Y-%m-%d")


def _parse_push_time(raw: Any) -> tuple[int, int]:
    """解析 HH:MM 形式的推送时间。

    Args:
        raw: 用户配置的推送时间，支持 ``23:00`` / ``23：00`` / ``2300``。

    Returns:
        (hour, minute) 元组；无法解析时回落到默认值 23:00。
    """
    text = str(raw or "").strip().replace("：", ":")
    match = re.fullmatch(r"(\d{1,2}):?(\d{2})", text)
    if not match:
        logger.warning(f"[{PLUGIN_NAME}] 推送时间格式不正确: {raw!r}，已回落为 {DEFAULT_PUSH_TIME}")
        return 23, 0
    hour, minute = int(match.group(1)), int(match.group(2))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        logger.warning(f"[{PLUGIN_NAME}] 推送时间超出范围: {raw!r}，已回落为 {DEFAULT_PUSH_TIME}")
        return 23, 0
    return hour, minute


def _decode_magnet_name(link: str) -> str:
    """从磁力链接的 dn= 参数中取出显示名称。

    Args:
        link: 磁力链接。

    Returns:
        解码后的名称；没有 dn 参数时返回空字符串。
    """
    query = link.split("?", 1)[-1]
    try:
        values = parse_qs(query, keep_blank_values=False).get("dn") or []
    except Exception:
        return ""
    if not values:
        return ""
    return re.sub(r"\s+", " ", unquote(values[0])).strip()


def _extract_btih(link: str) -> str:
    """从磁力链接中提取 BTIH 信息哈希（base32 会转成 hex）。

    Args:
        link: 磁力链接。

    Returns:
        小写哈希字符串；解析失败返回空字符串。
    """
    match = BTIH_RE.search(link)
    if not match:
        return ""
    raw = match.group(1)
    if len(raw) == 32:
        try:
            return base64.b32decode(raw.upper()).hex()
        except Exception:
            return raw.lower()
    return raw.lower()


def _collapse(text: str) -> str:
    """压缩空白字符，便于把多行名称归一化。

    Args:
        text: 原始文本。

    Returns:
        空白压缩后的文本。
    """
    return re.sub(r"\s+", " ", text or "").strip()


def _load_pil_image(path: Path) -> Any:
    """读取图片并转成 RGB（在线程池中调用，避免阻塞事件循环）。

    Args:
        path: 图片路径。

    Returns:
        PIL.Image.Image 对象；失败时抛出异常。
    """
    from PIL import Image as PILImage

    with PILImage.open(path) as img:
        return img.convert("RGB")


def _cover_crop(img: Any, width: int, height: int, focal_x: float = 0.5) -> Any:
    """按 cover 规则缩放并裁切图片，使其铺满目标尺寸。

    Args:
        img: 源 PIL 图片。
        width: 目标宽度。
        height: 目标高度。
        focal_x: 横向焦点（0-1），用于决定裁掉左边还是右边。

    Returns:
        目标尺寸的 PIL 图片。
    """
    from PIL import Image as PILImage

    ratio = max(width / img.width, height / img.height)
    resized = img.resize(
        (max(width, round(img.width * ratio)), max(height, round(img.height * ratio))),
        PILImage.LANCZOS,
    )
    left = int((resized.width - width) * min(max(focal_x, 0.0), 1.0))
    top = (resized.height - height) // 2
    return resized.crop((left, top, left + width, top + height))


class YcStatsPlugin(Star):
    """验车记录统计插件主类。"""

    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        """初始化插件，准备数据目录、读取历史记录并注册 Web API。

        Args:
            context: AstrBot 上下文。
            config: 由 ``_conf_schema.json`` 生成的插件配置（dict 子类）。
        """
        super().__init__(context)
        self.config: dict = config if config is not None else {}

        self.data_dir = Path(get_astrbot_plugin_data_path()) / PLUGIN_NAME
        self.image_dir = self.data_dir / "images"
        self.store_path = self.data_dir / "records.json"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.image_dir.mkdir(parents=True, exist_ok=True)

        self._io_lock = asyncio.Lock()
        self._scheduler_task: asyncio.Task | None = None
        self._live_groups_cache: tuple[float, list[dict]] = (0.0, [])
        self._font_warned = False
        self._background_cache: tuple[str, float, Any] = ("", 0.0, None)
        self._background_uri_cache: tuple[float, str] = (0.0, "")
        self._store = self._empty_store()
        self._load_store()
        self._register_web_apis()

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """插件激活时启动后台定时推送任务。

        Note:
            AstrBot 官方建议在 ``initialize()`` 中启动后台任务，
            ``context.register_task()`` 已弃用。
        """
        if self._scheduler_task and not self._scheduler_task.done():
            return
        self._scheduler_task = asyncio.create_task(
            self._scheduler_loop(), name=f"{PLUGIN_NAME}-scheduler"
        )
        now = datetime.now()
        logger.info(
            f"[{PLUGIN_NAME}] 已启动：记录={'开' if self._cfg('enabled', True) else '关'}"
            f"，定时推送={'开' if self._cfg('push_enabled', True) else '关'}"
            f"，推送时间 {self._cfg('push_time', DEFAULT_PUSH_TIME)}"
            f"（服务器本地时间 {now:%Y-%m-%d %H:%M}，时区 {time.tzname[0]}）"
            f"，白名单 {self._whitelist() or '（空=不限制）'}，数据目录 {self.data_dir}"
        )

    async def terminate(self) -> None:
        """插件被禁用/重载时取消后台任务并落盘。"""
        if self._scheduler_task and not self._scheduler_task.done():
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except (asyncio.CancelledError, Exception):
                pass
        self._scheduler_task = None
        await self._save_store()

    # ------------------------------------------------------------------
    # 配置读写
    # ------------------------------------------------------------------

    def _cfg(self, key: str, default: Any = None) -> Any:
        """读取插件配置项。

        Args:
            key: 配置键名。
            default: 缺省值。

        Returns:
            配置值，不存在时返回 ``default``。
        """
        try:
            return self.config.get(key, default)
        except Exception:
            return default

    def _triggers(self) -> list[str]:
        """返回生效的触发指令词列表（已过滤空值，长词优先）。"""
        raw = self._cfg("triggers", list(DEFAULT_TRIGGERS))
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, (list, tuple)):
            raw = list(DEFAULT_TRIGGERS)
        words = [str(item).strip() for item in raw if str(item).strip()]
        if not words:
            words = list(DEFAULT_TRIGGERS)
        return sorted(set(words), key=len, reverse=True)

    def _whitelist(self) -> list[str]:
        """返回群白名单（字符串群号列表，去重）。"""
        raw = self._cfg("whitelist_groups", [])
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, (list, tuple)):
            return []
        result: list[str] = []
        for item in raw:
            text = str(item).strip()
            if text and text not in result:
                result.append(text)
        return result

    def _save_config(self, values: dict) -> None:
        """写入插件配置（内存 + 磁盘），失败时记录日志。

        Args:
            values: 需要合并进配置的键值对。
        """
        self.config.update(values)
        save = getattr(self.config, "save_config", None)
        if callable(save):
            try:
                save()
            except Exception as e:
                logger.error(f"[{PLUGIN_NAME}] 保存插件配置失败: {e}")

    # ------------------------------------------------------------------
    # 存储层
    # ------------------------------------------------------------------

    @staticmethod
    def _empty_store() -> dict:
        """返回空的存储结构。"""
        return {
            "version": STORE_VERSION,
            "days": {},
            "groups": {},
            "pushes": {},
        }

    def _load_store(self) -> None:
        """从磁盘读取历史记录，损坏时自动备份并重建。"""
        if not self.store_path.is_file():
            return
        try:
            with self.store_path.open("r", encoding="utf-8") as fp:
                data = json.load(fp)
            if not isinstance(data, dict):
                raise ValueError("records.json 根节点不是对象")
            store = self._empty_store()
            days = data.get("days")
            if isinstance(days, dict):
                store["days"] = {
                    str(day): groups for day, groups in days.items() if isinstance(groups, dict)
                }
            groups = data.get("groups")
            if isinstance(groups, dict):
                store["groups"] = groups
            pushes = data.get("pushes")
            if isinstance(pushes, dict):
                store["pushes"] = pushes
            self._store = store
        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] 读取 {self.store_path} 失败，将重建: {e}")
            backup = self.store_path.with_suffix(f".broken-{int(time.time())}.json")
            try:
                self.store_path.replace(backup)
            except Exception:
                pass
            self._store = self._empty_store()

    async def _save_store(self) -> None:
        """异步原子写入存储文件。"""
        async with self._io_lock:
            payload = json.dumps(self._store, ensure_ascii=False, separators=(",", ":"))
            tmp_path = self.store_path.with_suffix(".tmp")
            try:
                await asyncio.to_thread(self._write_text, tmp_path, payload)
                await asyncio.to_thread(tmp_path.replace, self.store_path)
            except Exception as e:
                logger.error(f"[{PLUGIN_NAME}] 写入 {self.store_path} 失败: {e}")

    @staticmethod
    def _write_text(path: Path, text: str) -> None:
        """在线程中同步写文本文件。

        Args:
            path: 目标路径。
            text: 文本内容。
        """
        with path.open("w", encoding="utf-8") as fp:
            fp.write(text)

    def _prune_store(self) -> None:
        """按保留天数清理历史记录，并清理过期图片。"""
        keep_days = max(1, int(self._cfg("retention_days", 60) or 60))
        deadline = (datetime.now() - timedelta(days=keep_days)).strftime("%Y-%m-%d")
        days = self._store.get("days", {})
        for day in [d for d in days if d < deadline]:
            days.pop(day, None)
        pushes = self._store.get("pushes", {})
        for day in [d for d in pushes if d < deadline]:
            pushes.pop(day, None)
        self._cleanup_images(keep_days=3)

    def _cleanup_images(self, keep_days: int = 3) -> None:
        """删除过期的战报图片。

        Args:
            keep_days: 保留最近几天的图片。
        """
        deadline = time.time() - keep_days * 86400
        for path in self.image_dir.glob("*.jpg"):
            try:
                if path.stat().st_mtime < deadline:
                    path.unlink()
            except Exception:
                continue

    # ------------------------------------------------------------------
    # 消息记录
    # ------------------------------------------------------------------

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def on_group_message(self, event: AstrMessageEvent):
        """处理群消息：识别验车指令并记录/展示战报。

        Args:
            event: 群消息事件。

        Yields:
            AstrBot 消息结果（回执或战报图片）。

        Note:
            ``enabled`` 只控制「记录」；``#验车榜`` / ``#验车推送`` 与定时推送
            不受它影响，避免关掉记录后连推送一起失效。
        """
        group_id = event.get_group_id()
        if not group_id:
            return

        matched = self._match_trigger(event.get_message_str())
        if matched is None:
            return
        kind, body = matched

        if self._cfg("block_llm_reply", True):
            # 命中插件指令的消息不再交给 LLM / 后续默认流程处理
            event.stop_event()

        if kind == "preview":
            if not self._cfg("today_command", True):
                yield event.plain_result("本群已关闭战报查询（可在插件配置里开启「允许群内查询今日榜单」）。")
                return
            await self._remember_group(event)
            yield await self._reply_preview(event)
            return

        if kind == "push":
            allowed, reason = await self._can_manual_push(event)
            if not allowed:
                yield event.plain_result(reason)
                return
            await self._remember_group(event)
            sent = await self._push_groups([group_id], _today_str(), force=True)
            if sent and sent[0].get("ok"):
                yield event.plain_result("战报已推送。")
            else:
                reason = sent[0].get("error") if sent else "未知原因"
                yield event.plain_result(f"推送失败：{reason}")
            return

        if kind == "empty":
            yield event.plain_result(
                "用法：#验车 <磁力链接>\n"
                "例如：#验车 magnet:?xt=urn:btih:xxxxxxxx\n"
                "也可以用 #验车榜 查看今日战报。"
            )
            return

        if not self._cfg("enabled", True):
            # 记录开关关闭：只影响记录，不影响上面的查询/推送指令
            logger.debug(f"[{PLUGIN_NAME}] 记录已关闭（enabled=false），忽略群 {group_id} 的验车记录")
            return

        parsed = self._parse_yc_body(body)
        if not parsed:
            return

        whitelist = self._whitelist()
        if whitelist and group_id not in whitelist:
            logger.debug(f"[{PLUGIN_NAME}] 群 {group_id} 不在白名单，忽略记录")
            return

        entry, repeat = await self._record(event, group_id, parsed)
        if self._cfg("reply_receipt", False):
            flag = "重复" if repeat else "新增"
            yield event.plain_result(
                f"已记录（{flag}）：{entry['name']}\n该磁力今天第 {entry['count']} 次出现。"
            )

    async def _can_manual_push(self, event: AstrMessageEvent) -> tuple[bool, str]:
        """判断发送者是否有权手动推送战报。

        Args:
            event: 群消息事件。

        Returns:
            ``(是否允许, 拒绝时的提示文案)``。

        Note:
            允许三种人：AstrBot 管理员、群主/群管理员；拿不到群成员信息时不拦
            （部分平台不提供成员信息，避免把群主误拒）。
        """
        if self._is_admin(event):
            return True, ""
        sender_id = str(event.get_sender_id() or "")
        group = getattr(event.message_obj, "group", None)
        owner = getattr(group, "group_owner", None) if group else None
        admins = getattr(group, "group_admins", None) if group else None
        if not owner and not admins:
            # 事件里没有成员信息 → 主动问一次协议端（OneBot 系支持）
            try:
                resolved = await event.get_group()
                if resolved is not None:
                    group = resolved
                    owner = getattr(resolved, "group_owner", None)
                    admins = getattr(resolved, "group_admins", None)
            except Exception as e:
                logger.debug(f"[{PLUGIN_NAME}] 获取群成员信息失败: {e}")
        if owner or admins:
            if owner and str(owner) == sender_id:
                return True, ""
            if sender_id and sender_id in {str(item) for item in (admins or [])}:
                return True, ""
            return False, "只有群主/群管理员（或 AstrBot 管理员）可以手动推送战报。"
        return True, ""

    def _match_trigger(self, raw_text: str) -> tuple[str, str] | None:
        """判断消息是否命中验车指令。

        Args:
            raw_text: 事件中的纯文本消息。

        Returns:
            ``(kind, body)``；kind 为 ``record`` / ``preview`` / ``push`` / ``empty``，
            未命中时返回 ``None``。
        """
        text = AT_PREFIX_RE.sub("", _collapse(raw_text)).strip()
        if not text:
            return None
        for trigger in self._triggers():
            base = trigger.lstrip("#/")
            if not base:
                continue
            for prefix in (f"#{base}", f"/{base}", base):
                if not text.startswith(prefix):
                    continue
                head = text[len(prefix):].lstrip(TRIM_CHARS)
                if not head:
                    return "empty", ""
                if head in PREVIEW_WORDS:
                    return "preview", ""
                if head in PUSH_WORDS:
                    return "push", ""
                return "record", head
        return None

    @staticmethod
    def _is_admin(event: AstrMessageEvent) -> bool:
        """判断事件发送者是否为管理员。

        Args:
            event: 消息事件。

        Returns:
            是否为管理员。
        """
        checker = getattr(event, "is_admin", None)
        if callable(checker):
            try:
                return bool(checker())
            except Exception:
                return False
        return getattr(event, "role", "") == "admin"

    def _parse_yc_body(self, body: str) -> dict | None:
        """解析指令后面的内容，得到记录键、显示名称与磁力链接。

        Args:
            body: 指令词后面的文本（可能包含磁力链接和/或名称）。

        Returns:
            含 ``key`` / ``name`` / ``link`` / ``hash`` 的字典；无法解析时返回 ``None``。
        """
        text = _collapse(body)
        links = MAGNET_RE.findall(text)
        link = links[0] if links else ""
        info_hash = _extract_btih(link) if link else ""
        if not info_hash:
            hex_match = HEX40_RE.search(text)
            if hex_match:
                info_hash = hex_match.group(1).lower()
                if not link:
                    link = f"magnet:?xt=urn:btih:{info_hash}"

        # 名称候选 1：磁力链接里的 dn 参数
        name = _decode_magnet_name(link) if link else ""
        # 名称候选 2：剔除链接/哈希/指令词之后剩下的文本
        if not name:
            residual = text
            for item in links:
                residual = residual.replace(item, " ")
            residual = HEX40_RE.sub(" ", residual)
            name = _collapse(residual).strip(TRIM_CHARS)
        # 名称候选 3：退化成哈希前缀
        if not name:
            name = info_hash[:12] if info_hash else ""

        name = _collapse(name)
        if not name:
            return None

        max_len = max(1, int(self._cfg("name_max_len", DEFAULT_NAME_MAX_LEN) or DEFAULT_NAME_MAX_LEN))
        display_name = name[:max_len]

        if info_hash:
            key = f"hash:{info_hash}"
        else:
            digest = hashlib.sha1(name.lower().encode("utf-8")).hexdigest()[:16]
            key = f"name:{digest}"
        return {"key": key, "name": display_name, "link": link, "hash": info_hash}

    async def _remember_group(self, event: AstrMessageEvent, group_id: str = "") -> None:
        """记住群会话信息（umo/群名/平台），用于后续主动推送与 WebUI 展示。

        Args:
            event: 群消息事件。
            group_id: 群号，缺省时从事件中取。
        """
        gid = group_id or event.get_group_id()
        if not gid:
            return
        group_obj = getattr(event.message_obj, "group", None)
        group_name = getattr(group_obj, "group_name", "") or ""
        umo = getattr(event, "unified_msg_origin", "")
        info = self._store["groups"].setdefault(str(gid), {})
        changed = False
        for key, value in (
            ("umo", umo),
            ("name", group_name),
            ("platform", event.get_platform_name()),
            ("last_ts", time.time()),
        ):
            if value and info.get(key) != value:
                info[key] = value
                changed = True
        if changed:
            await self._save_store()

    async def _record(
        self, event: AstrMessageEvent, group_id: str, parsed: dict
    ) -> tuple[dict, bool]:
        """写入一条验车记录。

        Args:
            event: 群消息事件。
            group_id: 群号。
            parsed: ``_parse_yc_body`` 的解析结果。

        Returns:
            ``(记录条目, 是否为重复发送)``。
        """
        await self._remember_group(event, group_id)
        day = _today_str()
        self._prune_if_needed(day)

        bucket = self._store["days"].setdefault(day, {}).setdefault(group_id, {})
        entry = bucket.get(parsed["key"])
        now = time.time()
        sender_id = event.get_sender_id() or "unknown"
        sender_name = event.get_sender_name() or sender_id
        repeat = entry is not None
        if entry is None:
            entry = {
                "name": parsed["name"],
                "link": parsed["link"],
                "hash": parsed["hash"],
                "count": 0,
                "first_ts": now,
                "last_ts": now,
                "users": {},
            }
            bucket[parsed["key"]] = entry
        entry["count"] = int(entry.get("count", 0)) + 1
        entry["last_ts"] = now
        if parsed["name"] and len(parsed["name"]) > len(entry.get("name", "")):
            # 名称取更长的一次（同名链接的完整写法），仍受最大字数限制
            entry["name"] = parsed["name"]
        users = entry.setdefault("users", {})
        user = users.setdefault(sender_id, {"name": sender_name, "count": 0})
        user["count"] = int(user.get("count", 0)) + 1
        if sender_name:
            user["name"] = sender_name

        await self._save_store()
        logger.info(
            f"[{PLUGIN_NAME}] 记录 {day} 群{group_id} {entry['name']} 第 {entry['count']} 次"
        )
        return entry, repeat

    def _prune_if_needed(self, day: str) -> None:
        """跨天时清理过期数据。

        Args:
            day: 当前日期字符串。
        """
        last_day = self._store.get("last_seen_day")
        if last_day != day:
            self._store["last_seen_day"] = day
            self._prune_store()

    # ------------------------------------------------------------------
    # 背景图（毛玻璃底图）
    # ------------------------------------------------------------------

    def _background_path(self) -> Path | None:
        """解析当前生效的背景图路径。

        Returns:
            背景图路径；未启用或找不到文件时返回 ``None``。

        Note:
            查找顺序：配置 ``background_path`` → 插件数据目录 → 插件自带 ``resources/``。
        """
        if not self._cfg("background_enabled", True):
            return None
        custom = str(self._cfg("background_path", "") or "").strip()
        if custom:
            path = Path(custom)
            if not path.is_absolute():
                path = self.data_dir / path
            if path.is_file():
                return path
            logger.warning(f"[{PLUGIN_NAME}] 配置的背景图不存在，已忽略: {path}")
        for folder in (self.data_dir, PLUGIN_DIR / "resources"):
            for name in BACKGROUND_FILENAMES:
                candidate = folder / name
                if candidate.is_file():
                    return candidate
        return None

    def _background_image_sync(self):
        """同步读取背景图（供 Pillow 出图线程调用，按 mtime 缓存）。

        Returns:
            PIL 图片对象；不可用时返回 ``None``。
        """
        path = self._background_path()
        if path is None:
            return None
        try:
            stamp = path.stat().st_mtime
        except Exception:
            return None
        cached_path, cached_stamp, cached_image = self._background_cache
        if cached_image is not None and cached_path == str(path) and cached_stamp == stamp:
            return cached_image
        try:
            image = _load_pil_image(path)
        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] 背景图读取失败 {path}: {e}")
            return None
        self._background_cache = (str(path), stamp, image)
        return image

    async def _background_image(self):
        """异步读取背景图（内部走线程池）。

        Returns:
            PIL 图片对象；不可用时返回 ``None``。
        """
        return await asyncio.to_thread(self._background_image_sync)

    async def _background_uri(self) -> str:
        """把背景图编码成 base64 data URI，供 HTML 模板内嵌使用。

        Returns:
            ``data:image/jpeg;base64,...`` 字符串；不可用时返回空串。
        """
        path = self._background_path()
        if path is None:
            return ""
        try:
            stamp = await asyncio.to_thread(lambda: path.stat().st_mtime)
        except Exception:
            return ""
        cached_stamp, cached_uri = self._background_uri_cache
        if cached_uri and cached_stamp == stamp:
            return cached_uri

        def _encode() -> str:
            from PIL import Image as PILImage

            with PILImage.open(path) as img:
                img = img.convert("RGB")
                if img.width > BACKGROUND_EMBED_WIDTH:
                    height = round(img.height * BACKGROUND_EMBED_WIDTH / img.width)
                    img = img.resize((BACKGROUND_EMBED_WIDTH, height), PILImage.LANCZOS)
                buf = BytesIO()
                img.save(buf, "JPEG", quality=78, optimize=True)
                return base64.b64encode(buf.getvalue()).decode()

        try:
            encoded = await asyncio.to_thread(_encode)
        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] 背景图编码失败 {path}: {e}")
            return ""
        uri = f"data:image/jpeg;base64,{encoded}"
        self._background_uri_cache = (stamp, uri)
        return uri

    def _background_blur(self) -> int:
        """背景图毛玻璃模糊半径（像素，0-40）。"""
        try:
            value = int(self._cfg("background_blur", DEFAULT_BACKGROUND_BLUR))
        except (TypeError, ValueError):
            value = DEFAULT_BACKGROUND_BLUR
        return max(0, min(40, value))

    def _background_dim(self) -> int:
        """背景图白色蒙版强度（0-90，越大越"雾"）。"""
        try:
            value = int(self._cfg("background_dim", DEFAULT_BACKGROUND_DIM))
        except (TypeError, ValueError):
            value = DEFAULT_BACKGROUND_DIM
        return max(0, min(90, value))

    # ------------------------------------------------------------------
    # 战报数据 & 图片渲染
    # ------------------------------------------------------------------

    def _build_report(self, group_id: str, day: str) -> dict:
        """汇总某个群某天的战报数据。

        Args:
            group_id: 群号。
            day: 日期字符串（YYYY-MM-DD）。

        Returns:
            供图片渲染与 WebUI 使用的战报数据。
        """
        bucket = self._store.get("days", {}).get(day, {}).get(str(group_id), {})
        entries = list(bucket.values())
        top_n = max(1, int(self._cfg("push_top_n", 15) or 15))
        min_count = max(1, int(self._cfg("push_min_count", 1) or 1))
        qualified = [item for item in entries if int(item.get("count", 0)) >= min_count]
        qualified.sort(key=lambda item: (-int(item.get("count", 0)), item.get("name", "")))
        rows = qualified[:top_n]
        max_count = max((int(item.get("count", 0)) for item in rows), default=1)
        users: set[str] = set()
        for item in entries:
            users.update(item.get("users", {}).keys())
        group_info = self._store.get("groups", {}).get(str(group_id), {})
        return {
            "title": str(self._cfg("image_title", "今日验车战报") or "今日验车战报").strip(),
            "date": day,
            "group_id": str(group_id),
            "group_name": group_info.get("name") or f"群 {group_id}",
            "total_count": sum(int(item.get("count", 0)) for item in entries),
            "unique_count": len(entries),
            "user_count": len(users),
            "shown_count": len(rows),
            "more_count": max(0, len(qualified) - len(rows)),
            "rows": [
                {
                    "rank": index + 1,
                    "name": item.get("name", "") or "未命名",
                    "count": int(item.get("count", 0)),
                    "pct": round(int(item.get("count", 0)) / max_count * 100),
                    "cls": f"r{index + 1}" if index < 3 else "",
                    "link": item.get("link", ""),
                }
                for index, item in enumerate(rows)
            ],
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }

    async def _render_report(self, report: dict) -> Path | None:
        """渲染战报图片（HTML 优先，Pillow 兜底）。

        Args:
            report: ``_build_report`` 生成的数据。

        Returns:
            本地图片路径；渲染失败返回 ``None``。
        """
        mode = str(self._cfg("render_mode", "auto") or "auto").lower()
        path: Path | None = None
        if mode in ("auto", "html"):
            path = await self._render_report_html(report)
        if path is None and mode in ("auto", "pillow"):
            path = await asyncio.to_thread(self._render_report_pillow, report)
        if path is None:
            logger.error(f"[{PLUGIN_NAME}] 战报图渲染失败（mode={mode}）")
            return None
        target = self.image_dir / f"{report['date']}_{report['group_id']}.jpg"
        try:
            target.write_bytes(path.read_bytes())
            return target
        except Exception as e:
            logger.warning(f"[{PLUGIN_NAME}] 复制战报图失败，直接使用临时文件: {e}")
            return path

    async def _render_report_html(self, report: dict) -> Path | None:
        """使用 AstrBot 文转图（HTML/Jinja2）渲染战报。

        Args:
            report: 战报数据。

        Returns:
            本地图片路径；失败返回 ``None``。
        """
        data = {
            "title": html_lib.escape(report["title"]),
            "date": html_lib.escape(report["date"]),
            "group_name": html_lib.escape(report["group_name"]),
            "total_count": report["total_count"],
            "unique_count": report["unique_count"],
            "user_count": report["user_count"],
            "more_count": report["more_count"],
            "summary_line": html_lib.escape(
                f"共 {report['total_count']} 次发送 · {report['user_count']} 位群友参与"
            ),
            "generated_at": report["generated_at"],
            "bg_uri": await self._background_uri(),
            "bg_blur": self._background_blur(),
            "bg_dim": self._background_dim(),
            "bg_alpha": round(min(0.55, max(0.0, self._background_dim() / 180)), 2),
            "rows": [
                {**row, "name": html_lib.escape(row["name"])} for row in report["rows"]
            ],
        }
        try:
            path_str = await self.html_render(
                ANIME_TEMPLATE,
                data,
                return_url=False,
                options={"type": "jpeg", "quality": 90, "full_page": True},
            )
        except Exception as e:
            logger.warning(f"[{PLUGIN_NAME}] HTML 文转图失败，将尝试 Pillow 兜底: {e}")
            return None
        if not path_str:
            return None
        path = Path(str(path_str))
        if not path.is_file():
            logger.warning(f"[{PLUGIN_NAME}] 文转图未返回本地文件: {path_str}")
            return None
        return path

    def _render_report_pillow(self, report: dict) -> Path | None:
        """使用 Pillow 本地绘制二次元风格战报图（离线兜底方案）。

        Args:
            report: 战报数据。

        Returns:
            本地图片路径；失败返回 ``None``。
        """
        try:
            from PIL import Image as PILImage
            from PIL import ImageDraw, ImageFilter, ImageFont
        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] 未安装 Pillow，无法本地出图: {e}")
            return None

        width = 760
        rows = report["rows"]
        list_top = 292
        row_step = 66
        list_height = len(rows) * row_step if rows else 250
        footer_height = 62
        height = list_top + list_height + (26 if report["more_count"] else 0) + footer_height

        rng = random.Random(f"{report['date']}-{report['group_id']}")
        bg_image = self._background_image_sync()
        bg_blur = self._background_blur()
        bg_dim = self._background_dim()
        has_bg = bg_image is not None

        if has_bg:
            # 背景图 → 毛玻璃：cover 裁切 + 高斯模糊 + 轻雾化（保留照片色彩，鲸鱼娘仍可见）
            canvas = _cover_crop(bg_image, width, height, BACKGROUND_FOCAL_X).convert("RGBA")
            if bg_blur > 0:
                canvas = canvas.filter(ImageFilter.GaussianBlur(bg_blur))
            wash = PILImage.new("RGBA", (width, height), (255, 255, 255, round(255 * bg_dim / 100)))
            canvas = PILImage.alpha_composite(canvas, wash)
            from PIL import ImageEnhance

            canvas = ImageEnhance.Color(canvas).enhance(1.12)
        else:
            base = PILImage.new("RGB", (1, height))
            top_color = (255, 246, 251)
            bottom_color = (233, 243, 255)
            for y in range(height):
                ratio = y / max(1, height - 1)
                base.putpixel(
                    (0, y),
                    tuple(
                        int(top_color[i] + (bottom_color[i] - top_color[i]) * ratio)
                        for i in range(3)
                    ),
                )
            canvas = base.resize((width, height)).convert("RGBA")

        # 柔光色块，营造二次元渐变背景（叠在照片上时几乎不显示，避免糊掉底图）
        blob_alpha_scale = 0.10 if has_bg else 1.0
        blobs = PILImage.new("RGBA", (width, height), (0, 0, 0, 0))
        blob_draw = ImageDraw.Draw(blobs)
        for cx, cy, radius, color in (
            (60, 40, 190, (255, 214, 235, round(180 * blob_alpha_scale))),
            (width - 40, 150, 220, (214, 226, 255, round(170 * blob_alpha_scale))),
            (110, height - 60, 180, (255, 226, 244, 150)),
            (width - 90, height - 120, 160, (226, 236, 255, 130)),
        ):
            blob_draw.ellipse(
                [cx - radius, cy - radius, cx + radius, cy + radius], fill=color
            )
        canvas = PILImage.alpha_composite(canvas, blobs.filter(ImageFilter.GaussianBlur(30)))

        # 樱花花瓣装饰
        petals = PILImage.new("RGBA", (width, height), (0, 0, 0, 0))
        for _ in range(14):
            size = rng.randint(12, 26)
            petal = PILImage.new("RGBA", (size * 2, size * 2), (0, 0, 0, 0))
            petal_draw = ImageDraw.Draw(petal)
            petal_draw.ellipse(
                [0, 0, size * 2, int(size * 1.2)],
                fill=(
                    255,
                    rng.randint(160, 200),
                    rng.randint(200, 225),
                    round(rng.randint(90, 150) * (0.75 if has_bg else 1.0)),
                ),
            )
            petal = petal.rotate(rng.randint(0, 359), expand=True, resample=PILImage.BICUBIC)
            px = rng.choice([rng.randint(0, 150), rng.randint(width - 170, width - 30)])
            py = rng.randint(0, max(1, height - 40))
            petals.alpha_composite(petal, (max(0, px), max(0, py)))
        canvas = PILImage.alpha_composite(canvas, petals)

        draw = ImageDraw.Draw(canvas)
        # 有背景图时：标题区加一块毛玻璃面板，保证标题可读、同时不遮住照片
        if has_bg:
            draw.rounded_rectangle(
                [22, 12, width - 22, 144],
                radius=26,
                fill=(255, 255, 255, 70),
                outline=(255, 255, 255, 150),
                width=2,
            )
        title_font = self._load_font(38)
        sub_font = self._load_font(17)
        num_font = self._load_font(30)
        lab_font = self._load_font(14)
        name_font = self._load_font(21)
        count_font = self._load_font(19)
        foot_font = self._load_font(13)

        def center_text(text: str, y: int, font: Any, fill: tuple, shadow: bool = False) -> None:
            text_width = draw.textlength(text, font=font)
            x = (width - text_width) / 2
            if shadow:
                # 背景图上是浅色文字 → 先铺一层白晕，保证可读性
                draw.text((x, y + 1), text, font=font, fill=(255, 255, 255, 220))
                draw.text((x + 1, y), text, font=font, fill=(255, 255, 255, 170))
            draw.text((x, y), text, font=font, fill=fill)

        # 顶部标签
        tag_font = self._load_font(13)
        tag_text = "DAILY REPORT"
        tag_width = draw.textlength(tag_text, font=tag_font)
        draw.rounded_rectangle(
            [(width - tag_width) / 2 - 16, 26, (width + tag_width) / 2 + 16, 52],
            radius=13,
            fill=(255, 255, 255, 200 if has_bg else 235),
            outline=(255, 255, 255, 235) if has_bg else (255, 212, 233, 255),
            width=2 if has_bg else 1,
        )
        draw.text(
            ((width - tag_width) / 2, 31), tag_text, font=tag_font, fill=(179, 87, 138)
        )

        center_text(report["title"], 66, title_font, (201, 107, 166), shadow=has_bg)
        center_text(
            f"{report['date']} · {report['group_name']}",
            118,
            sub_font,
            (110, 96, 124) if has_bg else (139, 124, 148),
            shadow=has_bg,
        )

        # 三个统计胶囊
        stats = (
            (str(report["total_count"]), "总发送次数"),
            (str(report["unique_count"]), "不同磁力"),
            (str(report["user_count"]), "参与群友"),
        )
        chip_top, chip_height, gap = 156, 86, 14
        chip_width = (width - 52 * 2 - gap * 2) // 3
        for index, (number, label) in enumerate(stats):
            left = 52 + index * (chip_width + gap)
            draw.rounded_rectangle(
                [left, chip_top, left + chip_width, chip_top + chip_height],
                radius=20,
                fill=(255, 255, 255, 172 if has_bg else 225),
                outline=(255, 255, 255, 225) if has_bg else (255, 255, 255, 250),
                width=2 if has_bg else 1,
            )
            number_width = draw.textlength(number, font=num_font)
            draw.text(
                (left + (chip_width - number_width) / 2, chip_top + 14),
                number,
                font=num_font,
                fill=(224, 102, 159),
            )
            label_width = draw.textlength(label, font=lab_font)
            draw.text(
                (left + (chip_width - label_width) / 2, chip_top + 54),
                label,
                font=lab_font,
                fill=(139, 124, 148),
            )

        if rows:
            max_count = max(row["count"] for row in rows)
            for index, row in enumerate(rows):
                top = list_top + index * row_step
                draw.rounded_rectangle(
                    [40, top, width - 40, top + row_step - 12],
                    radius=18,
                    fill=(255, 255, 255, 196 if has_bg else 214),
                    outline=(255, 255, 255, 235) if has_bg else (255, 255, 255, 250),
                    width=2 if has_bg else 1,
                )
                # 排名徽章
                badge_colors = (
                    (255, 176, 68),
                    (168, 182, 199),
                    (231, 152, 106),
                )
                badge_color = badge_colors[index] if index < 3 else (203, 184, 214)
                draw.ellipse([56, top + 13, 88, top + 45], fill=badge_color)
                rank_text = str(row["rank"])
                rank_width = draw.textlength(rank_text, font=count_font)
                draw.text(
                    (72 - rank_width / 2, top + 20),
                    rank_text,
                    font=count_font,
                    fill=(255, 255, 255),
                )
                # 名称
                name_text = self._fit_text(draw, row["name"], name_font, width - 300)
                draw.text((102, top + 14), name_text, font=name_font, fill=(74, 59, 82))
                # 进度条
                bar_left, bar_top, bar_width, bar_height = 102, top + 44, width - 300, 7
                draw.rounded_rectangle(
                    [bar_left, bar_top, bar_left + bar_width, bar_top + bar_height],
                    radius=4,
                    fill=(242, 230, 240),
                )
                filled = int(bar_width * row["count"] / max_count)
                if filled > 0:
                    draw.rounded_rectangle(
                        [bar_left, bar_top, bar_left + max(filled, 10), bar_top + bar_height],
                        radius=4,
                        fill=(255, 168, 205),
                    )
                # 次数
                count_text = f"×{row['count']}"
                count_width = draw.textlength(count_text, font=count_font)
                draw.rounded_rectangle(
                    [
                        width - 56 - count_width - 26,
                        top + 16,
                        width - 56,
                        top + 50,
                    ],
                    radius=17,
                    fill=(255, 143, 192),
                )
                draw.text(
                    (width - 56 - count_width - 13, top + 22),
                    count_text,
                    font=count_font,
                    fill=(255, 255, 255),
                )
        else:
            face_center = (width // 2, list_top + 60)
            draw.ellipse(
                [
                    face_center[0] - 78,
                    face_center[1] - 70,
                    face_center[0] + 78,
                    face_center[1] + 60,
                ],
                fill=(255, 244, 250),
                outline=(255, 208, 228, 255),
                width=3,
            )
            for ear_x in (-52, 20):
                draw.polygon(
                    [
                        (face_center[0] + ear_x, face_center[1] - 62),
                        (face_center[0] + ear_x + 34, face_center[1] - 58),
                        (face_center[0] + ear_x + 8, face_center[1] - 96),
                    ],
                    fill=(255, 227, 241),
                    outline=(255, 208, 228),
                )
            for eye_x in (-34, 18):
                draw.ellipse(
                    [
                        face_center[0] + eye_x,
                        face_center[1] - 22,
                        face_center[0] + eye_x + 16,
                        face_center[1] + 2,
                    ],
                    fill=(107, 88, 117),
                )
            for blush_x in (-56, 32):
                draw.ellipse(
                    [
                        face_center[0] + blush_x,
                        face_center[1] + 6,
                        face_center[0] + blush_x + 24,
                        face_center[1] + 18,
                    ],
                    fill=(255, 195, 221),
                )
            draw.arc(
                [
                    face_center[0] - 14,
                    face_center[1] - 8,
                    face_center[0] + 14,
                    face_center[1] + 22,
                ],
                start=20,
                end=160,
                fill=(107, 88, 117),
                width=3,
            )
            empty_title = "今天还没有人验车哦"
            empty_width = draw.textlength(empty_title, font=name_font)
            draw.text(
                ((width - empty_width) / 2, list_top + 132),
                empty_title,
                font=name_font,
                fill=(179, 87, 138),
            )
            hint = "发送「#验车 磁力链接」即可上榜"
            hint_width = draw.textlength(hint, font=lab_font)
            draw.text(
                ((width - hint_width) / 2, list_top + 168),
                hint,
                font=lab_font,
                fill=(154, 138, 163),
            )

        footer_text_color = (110, 96, 124) if has_bg else (154, 138, 163)

        def footer_text(text: str, x: float, y: int) -> None:
            if has_bg:
                draw.text((x, y + 1), text, font=foot_font, fill=(255, 255, 255, 220))
            draw.text((x, y), text, font=foot_font, fill=footer_text_color)

        if report["more_count"]:
            more_text = f"… 还有 {report['more_count']} 条记录未展示"
            more_width = draw.textlength(more_text, font=lab_font)
            if has_bg:
                draw.text(
                    ((width - more_width) / 2, list_top + list_height + 5),
                    more_text,
                    font=lab_font,
                    fill=(255, 255, 255, 210),
                )
            draw.text(
                ((width - more_width) / 2, list_top + list_height + 4),
                more_text,
                font=lab_font,
                fill=footer_text_color,
            )

        footer_y = height - 44
        draw.line(
            [(40, footer_y - 10), (width - 40, footer_y - 10)],
            fill=(255, 255, 255, 210) if has_bg else (240, 217, 232),
            width=1,
        )
        summary = f"共 {report['total_count']} 次发送 · {report['user_count']} 位群友参与"
        footer_text(summary, 40, footer_y)
        stamp = f"{report['generated_at']} 生成"
        stamp_width = draw.textlength(stamp, font=foot_font)
        footer_text(stamp, width - 40 - stamp_width, footer_y)

        target = self.image_dir / (
            f"{report['date']}_{report['group_id']}_pillow{'_bg' if has_bg else ''}.jpg"
        )
        canvas.convert("RGB").save(target, "JPEG", quality=92)
        return target

    def _load_font(self, size: int, bold: bool = False) -> Any:
        """加载中文字体，优先插件数据目录下的自定义字体。

        Args:
            size: 字号。
            bold: 是否优先加载粗体。

        Returns:
            PIL.ImageFont 字体对象。
        """
        from PIL import ImageFont

        candidates: list[str] = []
        for name in ("font.ttf", "font.otf", "font-bold.ttf", "font.ttc"):
            candidates.append(str(self.data_dir / name))
        candidates.extend(
            [
                "C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc",
                "C:/Windows/Fonts/msyh.ttc",
                "C:/Windows/Fonts/simhei.ttf",
                "C:/Windows/Fonts/Deng.ttf",
                "/System/Library/Fonts/PingFang.ttc",
                "/System/Library/Fonts/Supplemental/Songti.ttc",
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
                "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
                "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
                "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/arphic/uming.ttc",
            ]
        )
        for candidate in candidates:
            try:
                if Path(candidate).is_file():
                    return ImageFont.truetype(candidate, size)
            except Exception:
                continue
        if not self._font_warned:
            logger.warning(
                f"[{PLUGIN_NAME}] 未找到中文字体，Pillow 出图可能显示方框。"
                f"可把中文字体放到 {self.data_dir / 'font.ttf'} 后重载插件。"
            )
            self._font_warned = True
        return ImageFont.load_default()

    @staticmethod
    def _fit_text(draw: Any, text: str, font: Any, max_width: float) -> str:
        """把文本裁剪到指定像素宽度内（超出部分用省略号）。

        Args:
            draw: PIL 绘图对象。
            text: 原始文本。
            font: 字体对象。
            max_width: 允许的最大宽度（像素）。

        Returns:
            适配宽度后的文本。
        """
        if draw.textlength(text, font=font) <= max_width:
            return text
        trimmed = text
        while trimmed and draw.textlength(trimmed + "…", font=font) > max_width:
            trimmed = trimmed[:-1]
        return (trimmed + "…") if trimmed else "…"

    async def _reply_preview(self, event: AstrMessageEvent):
        """生成并返回当前群今日战报图。

        Args:
            event: 群消息事件。

        Returns:
            AstrBot 消息结果。
        """
        report = self._build_report(event.get_group_id(), _today_str())
        path = await self._render_report(report)
        if path is None:
            return event.plain_result("战报图生成失败，请查看 AstrBot 日志。")
        return event.image_result(str(path))

    # ------------------------------------------------------------------
    # 定时推送
    # ------------------------------------------------------------------

    async def _scheduler_loop(self) -> None:
        """后台循环：到点执行每日推送（每 20 秒检查一次）。"""
        while True:
            try:
                await self._maybe_daily_push()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"[{PLUGIN_NAME}] 定时任务异常: {e}")
            await asyncio.sleep(20)

    async def _maybe_daily_push(self) -> None:
        """判断是否到达推送时间，满足条件则推送当天战报。

        Note:
            只看 ``push_enabled`` / ``push_time``，与记录开关 ``enabled`` 无关：
            关掉记录也应该照常推送（当天没记录时按 ``push_empty_report`` 决定）。
        """
        if not self._cfg("push_enabled", True):
            return
        day = _today_str()
        if self._store.get("last_push_day") == day:
            return
        if self._store.get("last_seen_day") != day:
            self._prune_if_needed(day)
        hour, minute = _parse_push_time(self._cfg("push_time", DEFAULT_PUSH_TIME))
        now = datetime.now()
        if (now.hour, now.minute) < (hour, minute):
            return
        self._store["last_push_day"] = day
        await self._save_store()
        targets = self._push_targets(day)
        if not targets:
            logger.warning(
                f"[{PLUGIN_NAME}] {day} 没有推送目标（白名单为空且当天无记录），已跳过每日推送"
            )
            return
        logger.info(
            f"[{PLUGIN_NAME}] 开始每日推送 {day}（服务器本地时间 {now:%Y-%m-%d %H:%M}），目标群 {targets}"
        )
        results = await self._push_groups(targets, day)
        ok_count = sum(1 for item in results if item.get("ok"))
        logger.info(f"[{PLUGIN_NAME}] 每日推送结束：成功 {ok_count}/{len(results)}，明细 {results}")

    def _push_targets(self, day: str) -> list[str]:
        """计算推送目标群列表。

        Args:
            day: 日期字符串。

        Returns:
            群号列表；白名单为空时取当天有记录的群。
        """
        whitelist = self._whitelist()
        if whitelist:
            return whitelist
        return sorted(self._store.get("days", {}).get(day, {}).keys())

    async def _push_groups(
        self, group_ids: list[str], day: str, force: bool = False
    ) -> list[dict]:
        """把某天的战报图推送到指定群。

        Args:
            group_ids: 目标群号列表。
            day: 日期字符串。
            force: 为 True 时忽略「当天无记录」限制。

        Returns:
            每个群的推送结果 ``[{"group_id", "ok", "error"}]``。
        """
        results: list[dict] = []
        for group_id in group_ids:
            group_id = str(group_id)
            report = self._build_report(group_id, day)
            if not report["unique_count"] and not (
                force or self._cfg("push_empty_report", False)
            ):
                logger.warning(
                    f"[{PLUGIN_NAME}] 群 {group_id} 当天没有记录，跳过推送"
                    "（如需空白战报请开启「无记录也推送空战报」）"
                )
                results.append({"group_id": group_id, "ok": False, "error": "当天无记录"})
                continue
            umo = await self._resolve_umo(group_id)
            if not umo:
                results.append(
                    {"group_id": group_id, "ok": False, "error": "无法确定会话（机器人不在该群？）"}
                )
                continue
            path = await self._render_report(report)
            if path is None:
                results.append({"group_id": group_id, "ok": False, "error": "战报图渲染失败"})
                continue
            caption = (
                f"{report['title']} · {day}\n"
                f"共 {report['total_count']} 次发送 / {report['unique_count']} 条磁力"
            )
            ok = False
            error = ""
            try:
                ok = await self.context.send_message(
                    umo,
                    MessageChain(chain=[Plain(caption), Image.fromFileSystem(str(path))]),
                )
            except Exception as e:
                error = str(e)
                logger.warning(f"[{PLUGIN_NAME}] 群 {group_id} 本地路径推送失败，改用 base64: {e}")
            if not ok:
                # 协议端与 AstrBot 不在同一台机器时 file:// 无效，改用 base64 直传
                try:
                    raw = await asyncio.to_thread(path.read_bytes)
                    ok = await self.context.send_message(
                        umo,
                        MessageChain(chain=[Plain(caption), Image.fromBytes(raw)]),
                    )
                    error = "" if ok else error
                except Exception as e:
                    error = str(e)
                    logger.error(f"[{PLUGIN_NAME}] 推送到群 {group_id} 失败: {e}")
            if ok:
                self._store.setdefault("pushes", {}).setdefault(day, {})[group_id] = time.time()
            results.append(
                {"group_id": group_id, "ok": bool(ok), "error": error or ("" if ok else "未找到对应平台")}
            )
            logger.info(f"[{PLUGIN_NAME}] 群 {group_id} 战报推送{'成功' if ok else '失败'}")
        if any(item["ok"] for item in results):
            await self._save_store()
        return results

    # ------------------------------------------------------------------
    # 群会话信息
    # ------------------------------------------------------------------

    async def _resolve_umo(self, group_id: str) -> str | None:
        """解析群号对应的 unified_msg_origin，用于主动推送。

        Args:
            group_id: 群号。

        Returns:
            ``platform_id:GroupMessage:group_id`` 形式的会话字符串；无法确定时返回 ``None``。
        """
        info = self._store.get("groups", {}).get(str(group_id))
        if info and info.get("umo"):
            return str(info["umo"])
        for item in await self._live_groups():
            if str(item.get("group_id")) != str(group_id):
                continue
            platform_id = item.get("platform_id")
            if platform_id:
                return f"{platform_id}:GroupMessage:{group_id}"
        return None

    def _platform_insts(self) -> list:
        """返回当前已加载的平台适配器实例列表。"""
        try:
            return list(self.context.platform_manager.get_insts())
        except Exception:
            return []

    async def _platform_group_list(self, inst) -> list[dict]:
        """通过平台适配器获取群列表（仅 OneBot 系适配器支持）。

        Args:
            inst: 平台适配器实例。

        Returns:
            群信息字典列表，形如 ``[{"group_id": "123", "group_name": "xx"}]``。
        """
        get_client = getattr(inst, "get_client", None)
        if not callable(get_client):
            return []
        api = getattr(get_client(), "api", None)
        if api is None or not hasattr(api, "call_action"):
            return []
        result = await asyncio.wait_for(api.call_action("get_group_list"), timeout=8)
        if isinstance(result, list):
            return [item for item in result if isinstance(item, dict)]
        return []

    async def _live_groups(self, ttl: int = 60) -> list[dict]:
        """获取机器人所在的群列表（带缓存）。

        Args:
            ttl: 缓存有效期（秒）。

        Returns:
            群信息字典列表。
        """
        cached_at, cached = self._live_groups_cache
        if cached and time.time() - cached_at < ttl:
            return cached
        groups: list[dict] = []
        for inst in self._platform_insts():
            try:
                meta = inst.meta()
                for item in await self._platform_group_list(inst):
                    item = dict(item)
                    item["group_id"] = str(item.get("group_id"))
                    item["platform"] = getattr(meta, "name", "")
                    item["platform_id"] = getattr(meta, "id", "")
                    groups.append(item)
            except Exception:
                continue
        if groups:
            self._live_groups_cache = (time.time(), groups)
        return groups

    # ------------------------------------------------------------------
    # Web API（供插件 Pages 调用）
    # ------------------------------------------------------------------

    def _register_web_apis(self) -> None:
        """注册插件 Pages 所需的 Web API 路由（带插件名前缀）。"""
        routes = (
            ("overview", self.api_overview, ["GET"], "验车记录概览"),
            ("stats", self.api_stats, ["GET"], "指定日期的明细数据"),
            ("whitelist", self.api_save_whitelist, ["POST"], "保存群白名单"),
            ("settings", self.api_save_settings, ["POST"], "保存推送设置"),
            ("preview", self.api_preview, ["POST"], "生成战报预览图"),
            ("push", self.api_push, ["POST"], "立即推送战报"),
            ("background", self.api_background, ["GET"], "背景图与毛玻璃参数"),
        )
        for route, handler, methods, desc in routes:
            try:
                self.context.register_web_api(
                    f"/{PLUGIN_NAME}/{route}", handler, methods, desc
                )
            except Exception as e:
                logger.error(f"[{PLUGIN_NAME}] 注册 Web API {route} 失败: {e}")

    async def api_overview(self):
        """返回插件概览数据：白名单、今日统计、可用群列表与推送设置。

        Returns:
            JSON 响应。
        """
        day = _today_str()
        days = self._store.get("days", {})
        today = days.get(day, {})
        live_groups = await self._live_groups()
        known: dict[str, dict] = {}
        for item in live_groups:
            gid = str(item.get("group_id"))
            known[gid] = {
                "group_id": gid,
                "group_name": item.get("group_name") or "",
                "source": "live",
            }
        for gid, info in self._store.get("groups", {}).items():
            known.setdefault(
                gid,
                {
                    "group_id": gid,
                    "group_name": info.get("name") or "",
                    "source": "record",
                },
            )
        whitelist = self._whitelist()
        group_rows = []
        for gid, info in sorted(known.items()):
            bucket = today.get(gid, {})
            group_rows.append(
                {
                    "group_id": gid,
                    "group_name": info.get("group_name") or "",
                    "source": info.get("source"),
                    "whitelisted": gid in whitelist,
                    "today_total": sum(int(v.get("count", 0)) for v in bucket.values()),
                    "today_unique": len(bucket),
                }
            )
        for gid in whitelist:
            if gid not in known:
                bucket = today.get(gid, {})
                group_rows.append(
                    {
                        "group_id": gid,
                        "group_name": "",
                        "source": "manual",
                        "whitelisted": True,
                        "today_total": sum(int(v.get("count", 0)) for v in bucket.values()),
                        "today_unique": len(bucket),
                    }
                )
        available_days = sorted(days.keys(), reverse=True)[:30]
        return json_response(
            {
                "plugin": PLUGIN_NAME,
                "today": day,
                "whitelist": whitelist,
                "groups": group_rows,
                "days": available_days,
                "settings": {
                    "enabled": bool(self._cfg("enabled", True)),
                    "today_command": bool(self._cfg("today_command", True)),
                    "reply_receipt": bool(self._cfg("reply_receipt", False)),
                    "block_llm_reply": bool(self._cfg("block_llm_reply", True)),
                    "push_enabled": bool(self._cfg("push_enabled", True)),
                    "push_time": self._cfg("push_time", DEFAULT_PUSH_TIME),
                    "push_top_n": int(self._cfg("push_top_n", 15) or 15),
                    "push_min_count": int(self._cfg("push_min_count", 1) or 1),
                    "push_empty_report": bool(self._cfg("push_empty_report", False)),
                    "name_max_len": int(self._cfg("name_max_len", DEFAULT_NAME_MAX_LEN) or DEFAULT_NAME_MAX_LEN),
                    "render_mode": str(self._cfg("render_mode", "auto") or "auto"),
                    "image_title": self._cfg("image_title", "今日验车战报"),
                    "background_enabled": bool(self._cfg("background_enabled", True)),
                    "background_path": str(self._cfg("background_path", "") or ""),
                    "background_blur": self._background_blur(),
                    "background_dim": self._background_dim(),
                    "background_source": str(self._background_path() or ""),
                    "triggers": self._triggers(),
                    "retention_days": int(self._cfg("retention_days", 60) or 60),
                },
                "last_push_day": self._store.get("last_push_day"),
                "pushes": self._store.get("pushes", {}).get(day, {}),
                "stats_total_days": len(days),
                "data_dir": str(self.data_dir),
            }
        )

    async def api_stats(self):
        """返回指定日期（可指定群）的明细榜单。

        Returns:
            JSON 响应。
        """
        day = request.query.get("date") or _today_str()
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(day)):
            return error_response("date 必须是 YYYY-MM-DD 格式")
        group_id = request.query.get("group_id") or ""
        group_id = str(group_id) if group_id else ""
        days = self._store.get("days", {}).get(str(day), {})
        if group_id and group_id not in days:
            days = {}
        entries = []
        for gid, bucket in days.items():
            if group_id and gid != group_id:
                continue
            for key, item in bucket.items():
                entries.append(
                    {
                        "key": key,
                        "group_id": gid,
                        "group_name": self._store.get("groups", {})
                        .get(gid, {})
                        .get("name", ""),
                        "name": item.get("name", ""),
                        "link": item.get("link", ""),
                        "count": int(item.get("count", 0)),
                        "first_ts": item.get("first_ts"),
                        "last_ts": item.get("last_ts"),
                        "user_count": len(item.get("users", {})),
                    }
                )
        entries.sort(key=lambda item: (-item["count"], item["name"]))
        return json_response({"date": str(day), "group_id": group_id, "entries": entries})

    async def api_save_whitelist(self):
        """保存群白名单。

        Returns:
            JSON 响应。
        """
        payload = await request.json(default={})
        raw = payload.get("groups") if isinstance(payload, dict) else None
        if raw is None:
            return error_response("缺少 groups 字段")
        if not isinstance(raw, list):
            return error_response("groups 必须是数组")
        if len(raw) > 200:
            return error_response("白名单最多 200 个群")
        groups: list[str] = []
        for item in raw:
            text = str(item).strip()
            if not text:
                continue
            if not re.fullmatch(r"[\w\-:@.]{1,64}", text):
                return error_response(f"群号格式不合法: {text}")
            if text not in groups:
                groups.append(text)
        self._save_config({"whitelist_groups": groups})
        logger.info(f"[{PLUGIN_NAME}] 白名单已更新: {groups}")
        return json_response({"whitelist": groups})

    async def api_save_settings(self):
        """保存推送与记录相关设置。

        Returns:
            JSON 响应。
        """
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("请求体必须是 JSON 对象")
        values: dict[str, Any] = {}
        if "enabled" in payload:
            values["enabled"] = bool(payload["enabled"])
        if "push_enabled" in payload:
            values["push_enabled"] = bool(payload["push_enabled"])
        if "push_empty_report" in payload:
            values["push_empty_report"] = bool(payload["push_empty_report"])
        if "reply_receipt" in payload:
            values["reply_receipt"] = bool(payload["reply_receipt"])
        if "block_llm_reply" in payload:
            values["block_llm_reply"] = bool(payload["block_llm_reply"])
        if "today_command" in payload:
            values["today_command"] = bool(payload["today_command"])
        if "push_time" in payload:
            raw_time = str(payload["push_time"]).strip()
            if not re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", raw_time):
                return error_response("推送时间格式应为 HH:MM（24 小时制）")
            values["push_time"] = raw_time
        if "image_title" in payload:
            values["image_title"] = str(payload["image_title"]).strip()[:32]
        if "background_enabled" in payload:
            values["background_enabled"] = bool(payload["background_enabled"])
        if "background_path" in payload:
            values["background_path"] = str(payload["background_path"]).strip()[:512]
        if "render_mode" in payload:
            mode = str(payload["render_mode"]).strip().lower()
            if mode not in ("auto", "html", "pillow"):
                return error_response("render_mode 只能是 auto / html / pillow")
            values["render_mode"] = mode
        for key, low, high in (
            ("push_top_n", 1, 50),
            ("push_min_count", 1, 999),
            ("name_max_len", 1, 64),
            ("retention_days", 1, 3650),
            ("background_blur", 0, 40),
            ("background_dim", 0, 90),
        ):
            if key in payload:
                try:
                    number = int(payload[key])
                except (TypeError, ValueError):
                    return error_response(f"{key} 必须是整数")
                if not (low <= number <= high):
                    return error_response(f"{key} 需在 {low}-{high} 之间")
                values[key] = number
        if not values:
            return error_response("没有可保存的字段")
        self._save_config(values)
        logger.info(f"[{PLUGIN_NAME}] 设置已更新: {values}")
        return json_response({"saved": values})

    async def api_preview(self):
        """生成战报预览图并按 data URI 返回（供插件 Pages 直接展示）。

        Returns:
            JSON 响应。
        """
        payload = await request.json(default={})
        day = _today_str()
        group_id = ""
        if isinstance(payload, dict):
            if payload.get("date"):
                day = str(payload["date"])
            if payload.get("group_id"):
                group_id = str(payload["group_id"])
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            return error_response("date 必须是 YYYY-MM-DD 格式")
        if not group_id:
            whitelist = self._whitelist()
            if whitelist:
                group_id = whitelist[0]
            else:
                bucket = self._store.get("days", {}).get(day, {})
                group_id = sorted(bucket.keys())[0] if bucket else ""
        report = self._build_report(group_id, day)
        path = await self._render_report(report)
        if path is None:
            return error_response("战报图渲染失败，请检查插件日志", status_code=500)
        try:
            raw = await asyncio.to_thread(path.read_bytes)
        except Exception as e:
            return error_response(f"读取预览图失败: {e}", status_code=500)
        if len(raw) > 3 * 1024 * 1024:
            return error_response("预览图过大，请在群里直接查看", status_code=413)
        encoded = base64.b64encode(raw).decode()
        return json_response(
            {
                "date": day,
                "group_id": group_id,
                "image": f"data:image/jpeg;base64,{encoded}",
                "total_count": report["total_count"],
                "unique_count": report["unique_count"],
            }
        )

    async def api_push(self):
        """立即推送当天战报（等价于定时推送）。

        Returns:
            JSON 响应。
        """
        payload = await request.json(default={})
        day = _today_str()
        groups: list[str] | None = None
        if isinstance(payload, dict):
            if payload.get("date"):
                day = str(payload["date"])
            raw_groups = payload.get("groups")
            if isinstance(raw_groups, list) and raw_groups:
                groups = [str(item).strip() for item in raw_groups if str(item).strip()]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            return error_response("date 必须是 YYYY-MM-DD 格式")
        targets = groups if groups else self._push_targets(day)
        if not targets:
            return error_response("没有推送目标：请先配置群白名单或保证当天有记录")
        results = await self._push_groups(targets, day, force=True)
        return json_response({"date": day, "results": results})

    async def api_background(self):
        """返回背景图（base64 data URI）与毛玻璃参数，供插件 Pages 使用。

        Returns:
            JSON 响应。
        """
        path = self._background_path()
        return json_response(
            {
                "enabled": bool(self._cfg("background_enabled", True)),
                "image": await self._background_uri(),
                "blur": self._background_blur(),
                "dim": self._background_dim(),
                "source": str(path) if path else "",
                "focal_x": BACKGROUND_FOCAL_X,
            }
        )

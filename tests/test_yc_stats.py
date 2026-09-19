"""本地验证脚本：用桩模块模拟 AstrBot，跑通验车插件的核心逻辑。

覆盖内容：
    1. 指令匹配（#验车 / 验车 / /验车 / #验车榜 / #验车推送）
    2. 磁力解析与名称截断（dn 参数 / 剩余文本 / 纯哈希）
    3. 按群按天计数 + 白名单过滤 + 持久化
    4. 战报数据汇总
    5. Web API（overview / stats / whitelist / settings / preview）
    6. HTML 模板 Jinja2 渲染与 Pillow 本地出图（输出到 tests/out/）

运行：
    E:\\astr插件\\_ref\\py\\python.exe E:\\astr插件\\tests/\test_yc_stats.py
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import shutil
import sys
import time
import types
from datetime import timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent
PLUGIN_DIR = (
    BASE.parent if (BASE.parent / "main.py").is_file() else BASE.parent / "astrbot_plugin_yc_stats"
)

OUT_DIR = BASE / "out"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# 测试数据落在工作目录内，避免写系统临时目录（部分环境对 TEMP 有写权限限制）
DATA_ROOT = OUT_DIR / "data"
DATA_ROOT.mkdir(parents=True, exist_ok=True)
_case_seq = 0


# ----------------------------------------------------------------------
# astrbot 桩模块
# ----------------------------------------------------------------------
class AstrBotConfig(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.saved = 0

    def save_config(self, replace=None, **kwargs):
        if replace:
            self.update(replace)
        self.saved += 1
        (DATA_ROOT / "config-dump.json").write_text(
            json.dumps(dict(self), ensure_ascii=False, indent=2), encoding="utf-8"
        )


class _Logger:
    def __init__(self):
        self.records: list[str] = []

    def _log(self, level, msg, *args):
        self.records.append(f"[{level}] {msg}")

    def info(self, msg, *a):
        self._log("INFO", msg)

    def warning(self, msg, *a):
        self._log("WARN", msg)

    def error(self, msg, *a):
        self._log("ERROR", msg)

    def debug(self, msg, *a):
        self._log("DEBUG", msg)


LOGGER = _Logger()


class MessageChain:
    def __init__(self, chain=None, **kwargs):
        self.chain = chain or []


class Image:
    def __init__(self, file=None, **kwargs):
        self.file = file

    @staticmethod
    def fromFileSystem(path, **kwargs):
        return Image(file=str(path))

    @staticmethod
    def fromURL(url, **kwargs):
        return Image(file=url)


class Plain:
    def __init__(self, text="", **kwargs):
        self.text = text


class EventMessageType:
    GROUP_MESSAGE = 1
    PRIVATE_MESSAGE = 2
    OTHER_MESSAGE = 4
    ALL = 7


class _FilterFactory:
    """收集装饰器注册的 handler，便于检查装饰器种类。"""

    def __init__(self):
        self.registered: list[tuple[str, object]] = []

    def _deco(self, kind):
        def wrapper(*args, **kwargs):
            def inner(func):
                self.registered.append((kind, func))
                return func

            return inner

        return wrapper

    def __getattr__(self, item):
        if item == "EventMessageType":
            return EventMessageType
        return self._deco(item)


FILTER = _FilterFactory()


class Star:
    def __init__(self, context, config=None):
        self.context = context
        self.config = config

    async def initialize(self):
        return None

    async def terminate(self):
        return None

    async def html_render(self, tmpl, data, return_url=True, options=None):
        """模拟文转图：本测试中故意失败，以验证 Pillow 兜底。"""
        raise RuntimeError("stub: t2i 服务不可用")

    async def text_to_image(self, text, return_url=True):
        raise RuntimeError("stub: t2i 服务不可用")


class Context:
    def __init__(self):
        self.routes: dict[str, tuple] = {}
        self.sent: list[tuple[str, MessageChain]] = []
        self.fail_sends = 0
        self.platform_manager = types.SimpleNamespace(get_insts=lambda: [])

    def register_web_api(self, route, handler, methods, desc):
        self.routes[route] = (handler, methods, desc)

    async def send_message(self, session, chain):
        if self.fail_sends > 0:
            self.fail_sends -= 1
            raise RuntimeError("stub: 模拟发送失败")
        self.sent.append((session, chain))
        return True


def _json_response(payload):
    return {"_json": payload}


def _error_response(message, status_code=400, data=None, headers=None):
    return {"_error": message, "_status": status_code}


class _RequestStub:
    def __init__(self):
        self.query = types.SimpleNamespace(get=self._get)
        self.payload = {}
        self.method = "GET"
        self.path = "/"
        self.plugin_name = "astrbot_plugin_yc_stats"
        self.username = "tester"

    def _get(self, key, default=None, type=None):
        value = self.query_values.get(key, default)
        if type is not None and value is not None:
            try:
                return type(value)
            except Exception:
                return default
        return value

    query_values: dict = {}

    async def json(self, default=None):
        return self.payload


REQUEST = _RequestStub()

_star_module = types.ModuleType("astrbot.api.star")
_star_module.Star = Star
_star_module.Context = Context

_web_module = types.ModuleType("astrbot.api.web")
_web_module.json_response = _json_response
_web_module.error_response = _error_response
_web_module.request = REQUEST
_web_module.file_response = lambda *a, **k: {"_file": a}
_web_module.stream_response = lambda *a, **k: {"_stream": a}

_event_module = types.ModuleType("astrbot.api.event")
_event_module.AstrMessageEvent = object
_event_module.MessageChain = MessageChain
_event_module.filter = FILTER

_api_module = types.ModuleType("astrbot.api")
_api_module.AstrBotConfig = AstrBotConfig
_api_module.logger = LOGGER

_components_module = types.ModuleType("astrbot.api.message_components")
_components_module.Image = Image
_components_module.Plain = Plain

_utils_module = types.ModuleType("astrbot.core.utils.astrbot_path")
_utils_module.get_astrbot_plugin_data_path = lambda: str(DATA_ROOT)

for name, module in (
    ("astrbot", types.ModuleType("astrbot")),
    ("astrbot.api", _api_module),
    ("astrbot.api.event", _event_module),
    ("astrbot.api.star", _star_module),
    ("astrbot.api.web", _web_module),
    ("astrbot.api.message_components", _components_module),
    ("astrbot.core", types.ModuleType("astrbot.core")),
    ("astrbot.core.utils", types.ModuleType("astrbot.core.utils")),
    ("astrbot.core.utils.astrbot_path", _utils_module),
):
    sys.modules[name] = module


def load_plugin_module():
    spec = importlib.util.spec_from_file_location(
        "astrbot_plugin_yc_stats", PLUGIN_DIR / "main.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["astrbot_plugin_yc_stats"] = module
    spec.loader.exec_module(module)
    return module


# ----------------------------------------------------------------------
# 假事件
# ----------------------------------------------------------------------
class FakeEvent:
    def __init__(self, text, group_id="123456", sender_id="10001", sender_name="阿伟",
                 group_name="测试群", role="member", platform="aiocqhttp"):
        self._text = text
        self._group_id = group_id
        self._sender_id = sender_id
        self._sender_name = sender_name
        self.role = role
        self._platform = platform
        self.unified_msg_origin = f"{platform}:GroupMessage:{group_id}"
        self.message_obj = types.SimpleNamespace(
            group=types.SimpleNamespace(group_id=group_id, group_name=group_name)
        )
        self.stopped = False
        self.results: list[object] = []

    def get_message_str(self):
        return self._text

    def get_group_id(self):
        return self._group_id

    def get_sender_id(self):
        return self._sender_id

    def get_sender_name(self):
        return self._sender_name

    def get_platform_name(self):
        return self._platform

    def stop_event(self):
        self.stopped = True

    def is_admin(self):
        return self.role == "admin"

    async def get_group(self, group_id=None):
        return self.message_obj.group

    def plain_result(self, text):
        result = ("plain", text)
        self.results.append(result)
        return result

    def image_result(self, path):
        result = ("image", path)
        self.results.append(result)
        return result


async def drain(agen, event):
    """把 async generator handler 的输出收集起来。"""
    async for _ in agen:
        pass
    return event.results


# ----------------------------------------------------------------------
# 测试用例
# ----------------------------------------------------------------------
class FakePlatform:
    """模拟 OneBot 平台适配器，用于验证「通过平台群列表解析会话」的路径。"""

    def __init__(self, platform_id, name, groups):
        self._platform_id = platform_id
        self._name = name
        self._groups = groups

    def meta(self):
        return types.SimpleNamespace(id=self._platform_id, name=self._name)

    def get_client(self):
        groups = self._groups

        class _Api:
            async def call_action(self, action):
                if action == "get_group_list":
                    return groups
                raise RuntimeError(f"unsupported action {action}")

        class _Client:
            def __init__(self):
                self.api = _Api()

        return _Client()


FAILURES: list[str] = []


def check(condition, label, extra=""):
    if condition:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label} {extra}")
        FAILURES.append(label)


def make_plugin(module, data_root=None, **config):
    """创建一个插件实例；默认使用独立数据目录，避免用例之间互相污染。"""
    global _case_seq
    if data_root is None:
        _case_seq += 1
        case_root = OUT_DIR / f"case-{_case_seq:02d}"
        if case_root.exists():
            shutil.rmtree(case_root, ignore_errors=True)
    else:
        case_root = Path(data_root)
    case_root.mkdir(parents=True, exist_ok=True)
    module.get_astrbot_plugin_data_path = lambda: str(case_root)
    cfg = AstrBotConfig(
        {
            "enabled": True,
            "triggers": ["#验车", "验车"],
            "name_max_len": 20,
            "whitelist_groups": [],
            "reply_receipt": True,
            "push_top_n": 15,
            "push_min_count": 1,
            "render_mode": "auto",
            "image_title": "今日验车战报",
            "retention_days": 60,
            **config,
        }
    )
    ctx = Context()
    plugin = module.YcStatsPlugin(ctx, cfg)
    return plugin, ctx, cfg


async def main():
    module = load_plugin_module()
    print("== 1. 指令匹配 ==")
    plugin, ctx, cfg = make_plugin(module)
    cases = [
        ("#验车 magnet:?xt=urn:btih:" + "a" * 40, "record"),
        ("验车 magnet:?xt=urn:btih:" + "b" * 40, "record"),
        ("/验车 magnet:?xt=urn:btih:" + "c" * 40, "record"),
        ("#验车榜", "preview"),
        ("#验车推送", "push"),
        ("#验车", "empty"),
        ("今天天气不错", None),
        ("#验车 abc", "record"),
    ]
    for text, expect in cases:
        matched = plugin._match_trigger(text)
        kind = matched[0] if matched else None
        check(kind == expect, f"_match_trigger({text[:24]!r}) -> {kind}", f"期望 {expect}")

    print("== 2. 磁力解析与截断 ==")
    long_name = "这是一个超级无敌长的磁力资源名称需要被截断处理哦"
    parsed = plugin._parse_yc_body(f"magnet:?xt=urn:btih:{'d'*40}&dn={long_name}")
    check(parsed is not None and len(parsed["name"]) == 20, "dn 名称截断到 20 字",
          f"实际 {parsed['name'] if parsed else None}")
    check(parsed["hash"] == "d" * 40, "dn 链接哈希解析")
    parsed2 = plugin._parse_yc_body(f"【自压】某资源 magnet:?xt=urn:btih:{'e'*40}")
    check(parsed2["name"] == "【自压】某资源", "从剩余文本取名称", f"实际 {parsed2['name']}")
    parsed3 = plugin._parse_yc_body("f" * 40)
    check(parsed3["hash"] == "f" * 40 and parsed3["link"].startswith("magnet:"),
          "纯 40 位哈希可识别")
    parsed4 = plugin._parse_yc_body("只有名字没有链接")
    check(parsed4 is not None and parsed4["hash"] == "" and parsed4["name"] == "只有名字没有链接",
          "纯名称记录")
    check(plugin._parse_yc_body("   ") is None, "空内容返回 None")

    print("== 3. 记录计数 / 白名单 / 回执 ==")
    plugin, ctx, cfg = make_plugin(module)
    link = f"magnet:?xt=urn:btih:{'1'*40}&dn=测试资源ABC"
    ev = FakeEvent(f"#验车 {link}")
    await drain(plugin.on_group_message(ev), ev)
    check(ev.stopped, "命中指令会拦截后续流程")
    check(ev.results and ev.results[0][0] == "plain", "开启回执时返回文本")
    same = str(link)
    ev2 = FakeEvent(f"#验车 {same}", sender_id="10002", sender_name="小明")
    await drain(plugin.on_group_message(ev2), ev2)
    day = module._today_str()
    bucket = plugin._store["days"][day]["123456"]
    entry = next(iter(bucket.values()))
    check(entry["count"] == 2, "同一链接计数累加", f"实际 {entry['count']}")
    check(len(entry["users"]) == 2, "记录不同发送者", f"实际 {entry['users']}")

    ev3 = FakeEvent(f"#验车 {link}", group_id="999")
    await drain(plugin.on_group_message(ev3), ev3)
    check(bool(plugin._store["days"][day].get("999")),
          "白名单为空时不限制群（999 也被记录）")

    plugin, ctx, cfg = make_plugin(module, whitelist_groups=["123456"], reply_receipt=False)
    ev4 = FakeEvent(f"#验车 {link}", group_id="888")
    await drain(plugin.on_group_message(ev4), ev4)
    check(not plugin._store["days"].get(module._today_str(), {}).get("888"), "白名单外的群不记录")
    ev5 = FakeEvent(f"#验车 {link}", group_id="123456")
    await drain(plugin.on_group_message(ev5), ev5)
    check(bool(plugin._store["days"][module._today_str()]["123456"]), "白名单内的群正常记录")
    check(not ev5.results, "关闭回执时无输出")

    print("== 3.5 记录开关只影响记录（enabled=false 时推送/查询仍可用）==")
    plugin_off, ctx_off, cfg_off = make_plugin(
        module, enabled=False, push_enabled=True, whitelist_groups=["123456"]
    )
    ev_rec = FakeEvent(f"#验车 {link}")
    await drain(plugin_off.on_group_message(ev_rec), ev_rec)
    check(
        not plugin_off._store["days"].get(module._today_str(), {}).get("123456"),
        "enabled=false 时不记录",
    )

    owner_ev = FakeEvent("#验车推送", sender_id="10001", role="member")
    owner_ev.message_obj.group.group_owner = "10001"
    owner_ev.message_obj.group.group_admins = []
    await drain(plugin_off.on_group_message(owner_ev), owner_ev)
    check(
        bool(owner_ev.results) and "战报已推送" in str(owner_ev.results[-1]),
        "enabled=false 时群主仍可手动推送",
        str(owner_ev.results),
    )
    check(len(ctx_off.sent) == 1, "手动推送真的调用了 send_message", str(ctx_off.sent))

    member_ev = FakeEvent("#验车推送", sender_id="20002", role="member")
    member_ev.message_obj.group.group_owner = "10001"
    member_ev.message_obj.group.group_admins = ["10005"]
    await drain(plugin_off.on_group_message(member_ev), member_ev)
    check(
        bool(member_ev.results) and "只有群主" in str(member_ev.results[-1]),
        "普通成员被拒绝手动推送",
        str(member_ev.results),
    )

    admin_ev = FakeEvent("#验车推送", sender_id="30003", role="admin")
    admin_ev.message_obj.group.group_owner = "10001"
    admin_ev.message_obj.group.group_admins = []
    await drain(plugin_off.on_group_message(admin_ev), admin_ev)
    check(
        bool(admin_ev.results) and "战报已推送" in str(admin_ev.results[-1]),
        "AstrBot 管理员可手动推送",
    )

    preview_ev = FakeEvent("#验车榜", role="member")
    await drain(plugin_off.on_group_message(preview_ev), preview_ev)
    check(
        bool(preview_ev.results) and preview_ev.results[-1][0] == "image",
        "enabled=false 时 #验车榜 仍可用",
        str(preview_ev.results),
    )

    # 定时推送同样不再受 enabled 影响（当天无记录时靠 push_empty_report 才发空战报）
    plugin_off._save_config({"push_empty_report": True})
    plugin_off._store["last_push_day"] = None
    cfg_off["push_enabled"] = True
    cfg_off["push_time"] = "00:00"
    before = len(ctx_off.sent)
    await plugin_off._maybe_daily_push()
    check(
        plugin_off._store.get("last_push_day") == module._today_str() and len(ctx_off.sent) == before + 1,
        "enabled=false 时定时推送照常执行",
        f"last_push_day={plugin_off._store.get('last_push_day')} sent={len(ctx_off.sent)}-{before}",
    )

    print("== 4. 战报数据 ==")
    ev6 = FakeEvent(f"#验车 {link}", sender_id="10003", sender_name="小红")
    await drain(plugin.on_group_message(ev6), ev6)
    report = plugin._build_report("123456", module._today_str())
    check(report["total_count"] == 2, "战报总次数", f"实际 {report['total_count']}")
    check(report["unique_count"] == 1, "战报去重条数", f"实际 {report['unique_count']}")
    check(report["rows"][0]["pct"] == 100 and report["rows"][0]["rank"] == 1, "榜单行数据")

    print("== 4.5 群友榜（发送者 + 次数）==")
    plugin_s, ctx_s, cfg_s = make_plugin(module, whitelist_groups=["123456"])
    link_s = f"magnet:?xt=urn:btih:{'9'*40}&dn=群友榜测试资源"
    for sender_id, sender_name in (("10001", "阿伟"), ("10001", "阿伟"), ("10002", "小明")):
        sender_ev = FakeEvent(f"#验车 {link_s}", sender_id=sender_id, sender_name=sender_name)
        await drain(plugin_s.on_group_message(sender_ev), sender_ev)
    rep = plugin_s._build_report("123456", module._today_str())
    check(
        [(s["name"], s["count"]) for s in rep["senders"]] == [("阿伟", 2), ("小明", 1)],
        "群友榜按次数降序且累加",
        str(rep["senders"]),
    )
    check(
        rep["sender_total"] == 2 and rep["user_count"] == 2,
        "群友榜人数与参与群友数一致",
        f"sender_total={rep['sender_total']} user_count={rep['user_count']}",
    )
    check(rep["senders"][0]["rank"] == 1 and rep["senders"][0]["cls"] == "s1", "群友榜名次标记")
    cfg_s["push_show_senders"] = False
    check(
        plugin_s._build_report("123456", module._today_str())["senders"] == [],
        "关闭开关后不输出群友榜",
    )
    cfg_s["push_show_senders"] = True
    cfg_s["push_sender_top_n"] = 1
    check(
        len(plugin_s._build_report("123456", module._today_str())["senders"]) == 1,
        "群友榜条数受 push_sender_top_n 限制",
    )
    cfg_s["push_sender_top_n"] = 5
    REQUEST.query_values = {"date": module._today_str(), "group_id": "123456"}
    stats_s = await plugin_s.api_stats()
    check(
        [(s["name"], s["count"]) for s in stats_s["_json"]["senders"]] == [("阿伟", 2), ("小明", 1)],
        "api_stats 返回群友榜",
        str(stats_s["_json"].get("senders")),
    )
    REQUEST.query_values = {}
    senders_pillow = await asyncio.to_thread(plugin_s._render_report_pillow, rep)
    check(senders_pillow is not None and senders_pillow.is_file(), "群友榜参与 Pillow 出图")
    if senders_pillow:
        (OUT_DIR / "senders-pillow.jpg").write_bytes(senders_pillow.read_bytes())

    print("== 5. Web API ==")
    check(len(ctx.routes) == 7, "注册 7 个 Web API 路由", f"实际 {sorted(ctx.routes)}")
    overview = await plugin.api_overview()
    data = overview["_json"]
    check(data["today"] == module._today_str(), "overview.today")
    check(data["whitelist"] == ["123456"], "overview.whitelist")
    check(any(g["group_id"] == "123456" and g["whitelisted"] for g in data["groups"]),
          "overview 群列表含白名单标记")
    REQUEST.query_values = {"date": module._today_str(), "group_id": "123456"}
    stats = await plugin.api_stats()
    check(stats["_json"]["entries"][0]["count"] == 2, "stats 明细计数")
    REQUEST.query_values = {}
    REQUEST.payload = {"groups": ["123456", "222", "bad id!"]}
    bad = await plugin.api_save_whitelist()
    check("_error" in bad, "非法群号被拒绝", str(bad))
    REQUEST.payload = {"groups": ["123456", "222"]}
    saved = await plugin.api_save_whitelist()
    check(saved["_json"]["whitelist"] == ["123456", "222"], "白名单保存")
    check(cfg["whitelist_groups"] == ["123456", "222"], "白名单写入配置")
    REQUEST.payload = {"push_time": "25:00"}
    check("_error" in await plugin.api_save_settings(), "非法时间被拒绝")
    REQUEST.payload = {"push_time": "22:30", "push_top_n": 5, "render_mode": "pillow"}
    ok = await plugin.api_save_settings()
    check(ok["_json"]["saved"]["push_time"] == "22:30", "设置保存")
    check(cfg["push_time"] == "22:30", "设置写入配置对象")

    print("== 6. 出图 ==")
    pillow_path = await asyncio.to_thread(plugin._render_report_pillow, report)
    check(pillow_path is not None and pillow_path.is_file(), "Pillow 本地出图")
    if pillow_path:
        size = pillow_path.stat().st_size
        check(size > 8000, "Pillow 图片体积合理", f"{size} bytes")
        target = OUT_DIR / "preview-pillow.jpg"
        target.write_bytes(pillow_path.read_bytes())
        print(f"  -> Pillow 预览图: {target}")
    report_empty = plugin._build_report("888888", module._today_str())
    empty_path = await asyncio.to_thread(plugin._render_report_pillow, report_empty)
    check(empty_path is not None and empty_path.is_file(), "空战报也能出图")
    if empty_path:
        (OUT_DIR / "preview-pillow-empty.jpg").write_bytes(empty_path.read_bytes())

    REQUEST.payload = {"date": module._today_str(), "group_id": "123456"}
    preview = await plugin.api_preview()
    check("_error" not in preview and preview["_json"]["image"].startswith("data:image/jpeg;base64,"),
          "api_preview 返回 data URI")

    print("== 6.5 背景图 + 毛玻璃 ==")
    bg_path = plugin._background_path()
    check(bg_path is not None and bg_path.name.startswith("background"),
          "找到插件自带背景图", str(bg_path))
    bg_uri = await plugin._background_uri()
    check(bg_uri.startswith("data:image/jpeg;base64,") and len(bg_uri) > 10000,
          "背景图编码为 data URI", f"长度 {len(bg_uri)}")
    bg_image = await plugin._background_image()
    check(bg_image is not None and bg_image.width >= 1000, "背景图可加载为 PIL 图片",
          str(getattr(bg_image, "size", None)))
    api_bg = await plugin.api_background()
    check(api_bg["_json"]["enabled"] and api_bg["_json"]["blur"] == 6 and api_bg["_json"]["dim"] == 14,
          "api_background 返回模糊/雾化参数",
          json.dumps(api_bg["_json"], ensure_ascii=False)[:100])
    glass_path = await asyncio.to_thread(plugin._render_report_pillow, report)
    check(glass_path is not None and glass_path.is_file(), "Pillow 毛玻璃版出图")
    plugin._save_config({"background_enabled": False})
    check(plugin._background_path() is None, "关闭开关后不再使用背景图")
    plain_path = await asyncio.to_thread(plugin._render_report_pillow, report)
    plain_again = await asyncio.to_thread(plugin._render_report_pillow, report)
    check(
        plain_path is not None
        and plain_path.name.endswith("_pillow.jpg")
        and plain_path.read_bytes() == plain_again.read_bytes(),
        "关闭背景图后输出纯渐变底（无 _bg 后缀、结果稳定）",
        str(plain_path),
    )
    plugin._save_config({"background_enabled": True})
    check(
        glass_path is not None
        and glass_path.name.endswith("_pillow_bg.jpg")
        and plain_path is not None
        and glass_path.read_bytes() != plain_path.read_bytes(),
        "启用背景图后出图结果不同（毛玻璃生效）",
    )
    if glass_path:
        (OUT_DIR / "preview-pillow-glass.jpg").write_bytes(glass_path.read_bytes())

    # 长榜单（竖版）验证背景裁切：鲸鱼娘应出现在画面上方
    tall_report = dict(report)
    tall_report["rows"] = [
        {
            "rank": index + 1,
            "name": f"【示例】某资源名称 {index + 1} 号",
            "count": 12 - index,
            "pct": max(10, 100 - index * 8),
            "cls": f"r{index + 1}" if index < 3 else "",
            "link": "",
        }
        for index in range(10)
    ]
    tall_report["more_count"] = 4
    tall_path = await asyncio.to_thread(plugin._render_report_pillow, tall_report)
    check(tall_path is not None and tall_path.is_file(), "竖版长榜单毛玻璃出图")
    if tall_path:
        (OUT_DIR / "preview-pillow-glass-tall.jpg").write_bytes(tall_path.read_bytes())

    print("== 7. 推送流程 ==")
    results = await plugin._push_groups(["123456"], module._today_str(), force=True)
    check(results[0]["ok"], "推送调用 send_message 成功", str(results))
    check(len(ctx.sent) == 1 and ctx.sent[0][0].endswith(":GroupMessage:123456"),
          "推送使用正确的 umo")
    check(len(ctx.sent[0][1].chain) == 2, "推送消息链包含文本 + 图片")
    results2 = await plugin._push_groups(["777"], module._today_str())
    check(not results2[0]["ok"] and results2[0]["error"] == "当天无记录", "无记录时跳过")

    print("== 7.5 群会话解析（平台群列表） ==")
    ctx.platform_manager = types.SimpleNamespace(
        get_insts=lambda: [
            FakePlatform("aiocqhttp", "aiocqhttp", [{"group_id": "555", "group_name": "新群"}])
        ]
    )
    plugin._live_groups_cache = (0.0, [])
    umo = await plugin._resolve_umo("555")
    check(umo == "aiocqhttp:GroupMessage:555", "通过平台群列表解析 umo", str(umo))
    overview_live = await plugin.api_overview()
    check(
        any(g["group_id"] == "555" and g["source"] == "live" for g in overview_live["_json"]["groups"]),
        "overview 展示机器人所在的群",
    )
    check(await plugin._resolve_umo("404404") is None, "未知群返回 None")

    print("== 8. 定时判断 ==")
    plugin._store["last_push_day"] = None
    cfg["push_enabled"] = True
    cfg["push_time"] = "00:00"
    await plugin._maybe_daily_push()
    check(plugin._store.get("last_push_day") == module._today_str(), "到点写入 last_push_day")
    sent_before = len(ctx.sent)
    await plugin._maybe_daily_push()
    check(len(ctx.sent) == sent_before, "同一天不重复推送")

    print("== 8.5 推送重试状态机 ==")
    plugin_r, ctx_r, cfg_r = make_plugin(
        module, whitelist_groups=["123456"], push_empty_report=True
    )
    # 模拟「该群会话已被记录」（机器人此前在本群收发过消息）
    plugin_r._store["groups"]["123456"] = {
        "umo": "aiocqhttp:GroupMessage:123456",
        "name": "测试群",
    }
    cfg_r["push_enabled"] = True
    cfg_r["push_time"] = "00:00"
    ctx_r.fail_sends = 1
    await plugin_r._maybe_daily_push()
    state = plugin_r._store.get("push_state") or {}
    check(
        state.get("attempts") == 1 and not state.get("done") and state.get("next_ts", 0) > time.time(),
        "推送失败：不标记完成 + 安排重试",
        str(state),
    )
    check(
        plugin_r._store.get("last_push_day") != module._today_str(),
        "推送失败不写 last_push_day（当天可重试）",
    )
    state["next_ts"] = 0  # 模拟重试时间已到
    await plugin_r._maybe_daily_push()
    check(
        (plugin_r._store.get("push_state") or {}).get("done") is True
        and plugin_r._store.get("last_push_day") == module._today_str(),
        "重试成功后标记当天完成",
        str(plugin_r._store.get("push_state")),
    )
    check(len(ctx_r.sent) == 1, "失败一次后重试成功，只成功送达一次", str(len(ctx_r.sent)))

    plugin_c, ctx_c, cfg_c = make_plugin(module, whitelist_groups=["123456"], push_empty_report=True)
    cfg_c["push_enabled"] = True
    cfg_c["push_time"] = "00:00"
    ctx_c.fail_sends = 99
    for _ in range(3):
        (plugin_c._store.setdefault("push_state", {}) or {})["next_ts"] = 0
        await plugin_c._maybe_daily_push()
    state_c = plugin_c._store.get("push_state") or {}
    check(
        state_c.get("attempts") == module.PUSH_MAX_ATTEMPTS and state_c.get("capped_logged"),
        f"连续失败 {module.PUSH_MAX_ATTEMPTS} 次后不再重试",
        str(state_c),
    )

    print("== 8.6 #验车状态 自检 ==")
    status_ev = FakeEvent("#验车状态", sender_id="10001", role="member")
    status_ev.message_obj.group.group_owner = "10001"
    await drain(plugin_r.on_group_message(status_ev), status_ev)
    status_text = str(status_ev.results[-1]) if status_ev.results else ""
    check(
        all(
            key in status_text
            for key in ("服务器本地时间", "定时推送", "在有白名单内" if False else "在白名单内", "今日记录", "推送会话")
        ),
        "#验车状态 返回自检信息",
        status_text[:120],
    )

    print("== 8.7 推送时区 ==")
    plugin_tz, _, cfg_tz = make_plugin(module, push_timezone="+08:00")
    check(plugin_tz._now().utcoffset() == timedelta(hours=8), "固定偏移 +08:00 生效",
          str(plugin_tz._now().utcoffset()))
    check(plugin_tz._today() == plugin_tz._now().strftime("%Y-%m-%d"), "日期跟随推送时区")
    cfg_tz["push_timezone"] = "UTC"
    check(plugin_tz._now().utcoffset() == timedelta(0), "UTC 时区生效")
    cfg_tz["push_timezone"] = "-05:00"
    check(plugin_tz._now().utcoffset() == timedelta(hours=-5), "负数偏移生效")
    cfg_tz["push_timezone"] = "garbage/zone"
    check(plugin_tz._zone() is None, "非法时区回退服务器本地时间")
    cfg_tz["push_timezone"] = ""
    check(plugin_tz._zone() is None, "留空 = 跟随服务器本地时间")
    cfg_tz["push_timezone"] = "Asia/Shanghai"
    zone = plugin_tz._zone()
    check(
        zone is not None and plugin_tz._now().utcoffset() == timedelta(hours=8),
        "Asia/Shanghai（北京时间）生效（无 tzdata 时按固定 +08:00 兜底）",
        str(zone),
    )
    cfg_tz["push_timezone"] = "local"
    check(plugin_tz._zone() is None, "local = 跟随服务器本地时间")
    # 北京时间 23:00 = UTC 15:00
    cfg_tz["push_timezone"] = "UTC"
    cfg_tz["push_time"] = "15:00"
    check(
        int(module._parse_push_time(cfg_tz["push_time"])[0]) + 8 == 23,
        "UTC 15:00 == 北京时间 23:00",
    )

    # 配置 schema：下拉选项与默认值
    schema = json.loads((module.PLUGIN_DIR / "_conf_schema.json").read_text(encoding="utf-8"))
    tz_field = schema["push_timezone"]
    check(
        tz_field["default"] == "Asia/Shanghai" and "Asia/Shanghai" in tz_field["options"],
        "push_timezone 默认 Asia/Shanghai 且为下拉选项",
        str(tz_field.get("default")),
    )
    check(
        len(tz_field.get("labels", [])) == len(tz_field["options"]),
        "下拉 labels 与 options 一一对应",
        f"{len(tz_field.get('labels', []))} vs {len(tz_field['options'])}",
    )
    # 每个下拉选项都必须能被 _zone() 解析（除 local 表示跟随服务器）
    for option in tz_field["options"]:
        cfg_tz["push_timezone"] = option
        resolved = plugin_tz._zone()
        if option == "local":
            check(resolved is None, "选项 local → 跟随服务器本地时间")
        else:
            check(resolved is not None, f"下拉选项 {option} 可解析", str(resolved))
    cfg_tz["push_timezone"] = "Asia/Shanghai"

    print("== 9. HTML 模板 ==")
    try:
        import jinja2
    except ImportError:
        print("  SKIP  未安装 jinja2，跳过模板渲染检查")
    else:
        env = jinja2.Environment(autoescape=False)
        template = env.from_string(module.ANIME_TEMPLATE)
        bg_uri_for_html = await plugin._background_uri()
        rows_html = template.render(
            title="今日验车战报",
            date=module._today_str(),
            group_name="测试群",
            total_count=report["total_count"],
            unique_count=report["unique_count"],
            user_count=report["user_count"],
            more_count=report["more_count"],
            summary_line="共 2 次发送 · 2 位群友参与",
            generated_at="2026-09-20 23:00",
            rows=report["rows"],
            bg_uri=bg_uri_for_html,
            bg_blur=6, bg_dim=14, bg_alpha=0.08,
            senders=rep["senders"], sender_total=rep["sender_total"],
        )
        (OUT_DIR / "preview-html.html").write_text(rows_html, encoding="utf-8")
        check("今日验车战报" in rows_html and "×2" in rows_html, "HTML 模板渲染出榜单")
        check("群友榜 · 今日验车次数" in rows_html and "阿伟" in rows_html, "HTML 模板渲染出群友榜")
        check("has-bg" in rows_html and "data:image/jpeg;base64," in rows_html
              and "backdrop-filter" in rows_html,
              "HTML 模板渲染出背景图层与毛玻璃样式")
        no_bg_html = template.render(
            title="今日验车战报",
            date=module._today_str(),
            group_name="测试群",
            total_count=report["total_count"],
            unique_count=report["unique_count"],
            user_count=report["user_count"],
            more_count=report["more_count"],
            summary_line="共 2 次发送",
            generated_at="2026-09-20 23:00",
            rows=report["rows"],
            bg_uri="",
            bg_blur=6, bg_dim=14, bg_alpha=0.08,
        )
        check('<div class="bg"' not in no_bg_html and "data:image/jpeg" not in no_bg_html,
              "无背景图时回落到纯渐变模板")
        empty_html = template.render(
            title="今日验车战报",
            date=module._today_str(),
            group_name="测试群",
            total_count=0,
            unique_count=0,
            user_count=0,
            more_count=0,
            summary_line="共 0 次发送",
            generated_at="2026-09-20 23:00",
            rows=[],
            bg_uri="",
            bg_blur=6, bg_dim=14, bg_alpha=0.08,
            empty_text=module.DEFAULT_EMPTY_REPORT_TEXT,
        )
        (OUT_DIR / "preview-html-empty.html").write_text(empty_html, encoding="utf-8")
        check(module.DEFAULT_EMPTY_REPORT_TEXT in empty_html, "HTML 空态渲染（摆烂文案）")
        check("Zzz" in empty_html, "空态渲染出 Zzz 装饰")
        print(f"  -> HTML 预览: {OUT_DIR / 'preview-html.html'}")

    print("== 9.5 空战报（摆烂图）==")
    schema_empty = json.loads(
        (module.PLUGIN_DIR / "_conf_schema.json").read_text(encoding="utf-8")
    )
    check(schema_empty["push_empty_report"]["default"] is True, "push_empty_report 默认开启")
    check(
        schema_empty["empty_report_text"]["default"] == module.DEFAULT_EMPTY_REPORT_TEXT,
        "空战报文案默认值正确",
    )
    rep_empty = plugin_s._build_report("999888", module._today_str())
    check(
        rep_empty["empty_text"] == module.DEFAULT_EMPTY_REPORT_TEXT and rep_empty["unique_count"] == 0,
        "战报数据带空态文案",
        rep_empty.get("empty_text"),
    )
    empty_pillow = await asyncio.to_thread(plugin_s._render_report_pillow, rep_empty)
    check(empty_pillow is not None and empty_pillow.is_file(), "空战报 Pillow 出图（摆烂猫）")
    if empty_pillow:
        (OUT_DIR / "empty-lazy-pillow.jpg").write_bytes(empty_pillow.read_bytes())
    ctx_s.fail_sends = 0
    sent_before = len(ctx_s.sent)
    await plugin_s._push_groups(["123456"], "2099-01-01", force=True)
    check(len(ctx_s.sent) == sent_before + 1, "空战报也会真的发出图片")
    if len(ctx_s.sent) > sent_before:
        caption_text = ctx_s.sent[-1][1].chain[0].text
        check(
            module.DEFAULT_EMPTY_REPORT_TEXT in caption_text,
            "空战报随图发送摆烂文案",
            caption_text,
        )

    print("== 10. 配置/存储落盘 ==")
    check((DATA_ROOT / "config-dump.json").is_file(), "配置已保存到磁盘")
    store_path = plugin.store_path
    plugin2, _, _ = make_plugin(module, data_root=plugin.data_dir.parent)
    check(store_path.is_file(), "records.json 已生成")
    check(bool(plugin2._store["days"]), "重载后能读回历史记录")

    print()
    if FAILURES:
        print(f"存在 {len(FAILURES)} 项失败: {FAILURES}")
        return 1
    print("全部通过 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))




# astrbot_plugin_yc_stats · 验车记录统计

记录群里 `#验车` 指令后面的磁力名称（只记录前 **20** 字），按「群 + 日期 + 链接」统计**同一个磁力链接一天被发送了几次**，
每晚 **23:00** 自动把当天战报渲染成**二次元风格图片**推送到群，并在 WebUI 提供**群白名单**管理页。

> 开发基线：AstrBot **v4.28.1**（2026-09-14）最新插件规范
> —— `Star` + `@filter` 装饰器、`_conf_schema.json` 配置、`context.register_web_api()` + `astrbot.api.web`、
> 插件 Pages（`pages/<name>/index.html` + `window.AstrBotPluginPage` bridge）、`Star.html_render()` 文转图。

---

## 1. 功能一览

| 功能 | 说明 |
| --- | --- |
| 记录 | 群消息以 `#验车` / `验车`（可带 `/` 前缀）开头即记录；名称只保留前 20 字（可配置） |
| 计数 | 按 **群 + 日期 + 链接** 计数，同一个链接被重复发送会累加，并记录参与成员与昵称 |
| 去重维度 | 优先用磁力链接的 BTIH 哈希作为唯一键；没有链接时用名称文本作为键 |
| 定时推送 | 每天 23:00（可配置）自动推送当天战报图，跨重启不会重复推送 |
| 群白名单 | 只有白名单内的群会被记录与推送；留空 = 不限制（所有群都记录，推送给当天有记录的群） |
| 出图 | 二次元风格战报图：默认走 AstrBot 文转图（HTML/Jinja2），失败自动降级 **Pillow 本地绘制** |
| Web 页面 | 可视化维护白名单、推送时间、上榜条数/门槛、出图方式，并支持**预览**与**立即推送** |
| 手动查询 | `#验车榜` 立即返回当前群当天的战报图；`#验车推送`（群管理员）手动补发 |

## 2. 安装

1. 把整个 `astrbot_plugin_yc_stats` 目录放到 `AstrBot/data/plugins/` 下：

   ```text
   AstrBot/
   └─ data/
      └─ plugins/
         └─ astrbot_plugin_yc_stats/
            ├─ main.py
            ├─ metadata.yaml
            ├─ _conf_schema.json
            ├─ requirements.txt
            ├─ logo.png
            ├─ pages/whitelist/{index.html,app.js,style.css}
            ├─ resources/background.jpg
            └─ .astrbot-plugin/i18n/{zh-CN.json,en-US.json}
   ```

2. 在 WebUI「插件」页面点击 **重载插件**（或重启 AstrBot）。首次加载会自动 `pip install Pillow`（见 `requirements.txt`）。
3. 打开 **插件详情 → 验车记录 · 群白名单** 页面配置群白名单与推送时间。

> 也可以打包成 zip 后在 WebUI 上传安装（打包时请保留 `pages/` 与 `.astrbot-plugin/` 两个目录）。

### 版本要求

* 记录 / 计数 / 定时推送 / 出图：`AstrBot >= 4.16`
* Web 可视化页面（插件 Pages）：`AstrBot >= 4.24.2`（该版本才引入插件 Pages）
  更低版本请在 **插件配置** 里直接编辑「群白名单」列表，功能等价。

## 3. 指令

| 指令 | 权限 | 说明 |
| --- | --- | --- |
| `#验车 <磁力链接>` | 所有人 | 记录一次。支持 `magnet:?xt=urn:btih:...`、40 位 BTIH 纯哈希，也支持「名称 + 链接」一起发 |
| `#验车 <名称>` | 所有人 | 没有链接时按名称记录（同一名称同样累加次数） |
| `#验车榜` | 所有人 | 立即生成并返回当前群当天战报图 |
| `#验车推送` | 群主 / 群管理员 / AstrBot 管理员 | 立即推送当前群当天战报（用于补发/测试；没有记录时也会发一张空战报，方便验证链路） |
| `#验车状态` | 群主 / 群管理员 / AstrBot 管理员 | 返回一条自检信息：服务器本地时间与时区、推送设置、白名单、本群是否在白名单内、今日记录数、推送会话、今日推送状态与最近结果 |
| `#验车` | 所有人 | 返回用法提示 |

名称解析优先级：**链接 `dn=` 参数 → 指令后面的剩余文本 → 哈希前 12 位**，随后按配置截断到前 N 字。

命中指令的消息默认会被 `event.stop_event()` 拦截，不再交给 LLM，避免机器人对着磁力链接乱答（可通过配置 `block_llm_reply` 关闭）。

## 4. 配置项（`_conf_schema.json`）

| 配置 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `enabled` | bool | `true` | **只控制「记录」**；关掉后不再记录新数据，但定时推送与 `#验车榜` / `#验车推送` 仍可用 |
| `triggers` | list | `["#验车","验车"]` | 触发词，可自定义多个 |
| `name_max_len` | int | `20` | 名称保留字数 |
| `whitelist_groups` | list | `[]` | 群白名单（留空 = 不限制） |
| `reply_receipt` | bool | `false` | 记录后是否在群里回执 |
| `block_llm_reply` | bool | `true` | 命中指令是否拦截其它自动回复 |
| `today_command` | bool | `true` | 是否允许 `#验车榜` |
| `push_enabled` | bool | `true` | 每日推送开关 |
| `push_time` | string | `23:00` | 推送时间（24 小时制 HH:MM） |
| `push_top_n` | int | `15` | 战报图最多显示条数 |
| `push_min_count` | int | `1` | 上榜门槛 |
| `push_empty_report` | bool | `false` | 当天无记录是否也推送空战报 |
| `render_mode` | string | `auto` | `auto` / `html` / `pillow`，见下文出图机制 |
| `image_title` | string | `今日验车战报` | 战报图标题 |
| `background_enabled` | bool | `true` | 是否使用背景图（毛玻璃底图） |
| `background_path` | string | `""` | 自定义背景图路径；留空则查数据目录 → 插件 `resources/` |
| `background_blur` | int | `6` | 背景图高斯模糊半径（0-40 px） |
| `background_dim` | int | `14` | 背景图白色雾化强度（0-90，越大越白越朦胧） |
| `retention_days` | int | `60` | 历史记录保留天数 |

## 4.1 背景图与毛玻璃

* 插件内置随包分发的背景图 `resources/background.jpg`（1920×1080，由「鲸鱼娘.png」生成）。
* **换成自己的图**（按优先级）：
  1. 配置 `background_path` 指向图片（相对路径按插件数据目录解析）；
  2. 把图片命名成 `background.jpg / png / webp`（或 `bg.*`）放进
     `data/plugin_data/astrbot_plugin_yc_stats/`——覆盖内置图，且升级插件不丢；
  3. 直接替换插件目录下的 `resources/background.jpg`。
* 合成顺序：底图 cover 裁切 → 高斯模糊（`background_blur`）→ 白色雾化（`background_dim`）→ 上方叠半透明毛玻璃卡片。
* 调参建议：**想看清背景人物** → 模糊 0-3、雾化 0-10；**想更朦胧** → 模糊 12-20、雾化 40-70。
  群里的战报图（HTML 与 Pillow 两条渲染路径）和插件页面共用同一套参数。
* 竖版战报按「横向 32% 焦点」裁切（鲸鱼娘偏画面左侧，避免被裁掉）；横版取中间高度带。

## 5. Web 页面（插件 Pages）

页面目录：`pages/whitelist/`，通过 `window.AstrBotPluginPage` bridge 调用后端：

| HTTP | 路由（注册时带插件名前缀） | 作用 |
| --- | --- | --- |
| GET | `/astrbot_plugin_yc_stats/overview` | 概览：白名单、可用群列表、今日统计、当前设置 |
| GET | `/astrbot_plugin_yc_stats/stats` | 指定日期/群的明细榜单 |
| POST | `/astrbot_plugin_yc_stats/whitelist` | 保存群白名单（校验群号格式，最多 200 个） |
| POST | `/astrbot_plugin_yc_stats/settings` | 保存推送/记录设置（校验时间格式与数值范围） |
| POST | `/astrbot_plugin_yc_stats/preview` | 生成战报预览图（base64 data URI） |
| POST | `/astrbot_plugin_yc_stats/push` | 立即推送（返回每个群的成功/失败原因） |
| GET | `/astrbot_plugin_yc_stats/background` | 背景图 data URI 与毛玻璃参数（供页面渲染底图） |

页面上的「生成预览」只在网页显示，不会发到群里；「立即推送」会真的发送。
页面里的「背景图 · 毛玻璃」区块可以实时拖动滑块调整模糊/雾化并立即看到效果。

## 6. 出图机制（重要）

1. `render_mode=auto`（默认）：先调用 AstrBot 官方 `Star.html_render()`，把二次元风格 HTML/Jinja2 模板渲染成图片。
   * 该能力实际由 **网络文转图服务** 完成（默认端点 `https://t2i.soulter.top/text2img`，AstrBot 会异步拉取可用端点列表）。
   * 服务器无法访问外网 / 端点不可用时，AstrBot 官方并无本地兜底（`html_render` 会直接抛错）。
2. 因此插件内置 **Pillow 本地绘制兜底**：渐变背景 + 樱花花瓣 + 圆角卡片 + 排名徽章 + 进度条，离线也能出二次元风格战报图。

### 中文显示方框怎么办？

Pillow 兜底需要中文字体。插件会依次查找：
`data/plugin_data/astrbot_plugin_yc_stats/font.ttf`（推荐）→ Windows 微软雅黑 → Linux Noto CJK / 文泉驿 → macOS PingFang。
若日志出现「未找到中文字体」，把任意中文字体重命名为 `font.ttf` 放进上述数据目录后重载插件即可。

## 7. 数据存储

所有运行期数据都写在 `AstrBot/data/plugin_data/astrbot_plugin_yc_stats/`（**不写插件目录**，升级/重装插件不丢数据）：

```text
plugin_data/astrbot_plugin_yc_stats/
├─ records.json                     # 记录与计数
├─ font.ttf                         # 可选：Pillow 出图用的中文字体
├─ background.jpg                   # 可选：自定义背景图（覆盖内置图）
└─ images/
   ├─ 2026-09-20_123456.jpg         # 每日战报图（保留 3 天，用于网页预览）
   ├─ 2026-09-20_123456_pillow_bg.jpg  # Pillow 毛玻璃版（带 _bg 表示用了背景图）
   └─ ...
```

`records.json` 结构（简）：

```json
{
  "version": 1,
  "last_push_day": "2026-09-20",
  "days": {
    "2026-09-20": {
      "123456": {
        "hash:<btih>": {
          "name": "只保留前20字的名称",
          "link": "magnet:?xt=urn:btih:...",
          "hash": "<btih>",
          "count": 3,
          "first_ts": 1758300000.0,
          "last_ts": 1758380000.0,
          "users": { "10001": { "name": "昵称", "count": 2 } }
        }
      }
    }
  },
  "groups": { "123456": { "umo": "aiocqhttp:GroupMessage:123456", "name": "群名" } },
  "pushes": { "2026-09-20": { "123456": 1758380400.0 } }
}
```

## 8. 常见问题

* **推送没动静，怎么排查？** 在群里（群主/群管理员）发一条 **`#验车状态`**，它会直接告诉你：
  服务器本地时间与时区、`push_enabled`/`push_time`、白名单、**本群是否在白名单内**、今日记录数、
  推送会话能否解析（`platform_id:GroupMessage:群号`）、今日推送状态与最近一次结果。
  服务端日志里搜 `astrbot_plugin_yc_stats` 也能看到同样的信息。常见原因：
  1. **群号不对**：白名单里的群号与实际群号不一致 → 记录会被白名单拦掉（日志写「群 X 不在白名单」，自检显示 ❌）。
     建议在插件页「群白名单」里**勾选**机器人所在的群，而不是手打群号。
  2. **时区**：`push_time` 用的是 **AstrBot 所在机器的本地时间**。若你在 UTC+8、服务器是 UTC，填 `23:00`
     实际会在北京时间次日 07:00 推送 —— 自检第一行会显示 `UTC+00:00` 这类偏移，照它换算（要北京时间 23:00 → 填 `15:00`）。
  3. **当天没有记录**：`push_empty_report=false` 时不发空战报（自检里「今日记录 0 条」即可确认）。
  4. **机器人当时不在线**：定时任务在插件 `initialize()` 里启动，23:00 进程没跑就会错过。
  5. **会话没解析到**：自检里「推送会话」显示 ⚠️ → 让机器人在该群收发一条消息，或确认机器人在群、群号在 `get_group_list` 中。
  6. **失败会自动重试**：全部失败时每 5 分钟重试一次、最多 3 次；只有「至少一个群成功」才把当天标记为完成。
* **同一链接算几次？** 同一条消息里重复出现同一链接只算一次；不同群分别计数；跨天自动分桶。
* **白名单留空是什么意思？** 不限制：所有群都记录；推送时目标为当天有记录的群。想「只记录指定群」就把群号填进白名单。
* **「启用验车记录」关了会怎样？** 只是不再记录新的 `#验车`；`#验车榜`、`#验车推送`、定时推送都不受影响。
* **`#验车` 会不会触发 LLM 回复？** 默认不会（`block_llm_reply=true` 会拦截）；若你希望同时让其它插件/LLM 处理，把它关掉。
* **能否给别的平台用？** 记录与推送基于通用 `AstrMessageEvent` / `context.send_message`，适配器只要支持主动发消息即可；
  「自动发现群列表」目前只对 OneBot 系（aiocqhttp）生效，其它平台请手动填写群号，或让机器人先在群里收到一次消息。

## 9. 开发与自测

仓库内 `tests/` 提供了不依赖 AstrBot 的桩模块测试（模拟装饰器、事件、Web 请求），覆盖：

```
指令匹配 / 磁力解析与截断 / 计数与白名单 / 战报汇总 / Web API / 出图 / 背景图与毛玻璃 / 推送 / 定时判断 / 模板渲染 / 持久化
```

```bash
python tests/test_yc_stats.py          # 全量逻辑自测（输出到 tests/out/）
python tests/make_logo.py              # 重新生成 logo.png
python tests/make_background_asset.py  # 把素材图处理成 resources/background.jpg
python tests/bg_variants.py            # 批量对比不同毛玻璃参数下的出图效果
python tests/make_page_preview.py      # 生成带 mock bridge 的页面预览（浏览器打开 tests/out/page/index.html）
python tests/pack_zip.py               # 打成可安装/可发布的 zip（自动排除缓存与测试产物）
```

测试数据、预览图都落在 `tests/out/`（已在 `.gitignore` 中忽略）。

修改代码后建议按 AstrBot 官方要求执行 `ruff format .` 与 `ruff check .`。

## 10. 发布到 AstrBot 插件市场

1. 插件仓库根目录即插件根目录（`main.py` / `metadata.yaml` 在最外层），`metadata.yaml` 的
   `author` 与 `repo` 需与 GitHub 仓库 owner/地址一致（当前为 `jusanlius/astrbot_plugin_yc_stats`）。
2. 发版时同步更新 `metadata.yaml` 的 `version`，打 tag 并推送。
3. 到 <https://cloud.astrbot.app/publish> 提交（需注册 AstrBot Cloud）；CI 会校验仓库、元数据，并要求压缩包 ≤ 16MB。
4. 打包用 `python tests/pack_zip.py`：自动排除 `.git`、`__pycache__`、`tests/out/`、`*.zip`（`.gitignore` 也覆盖了这些）。
5. 若改动插件目录名，请同步修改 `main.py` 顶部 `PLUGIN_NAME` 与 `metadata.yaml` 的 `name`
   （两者需一致，Web API 路由前缀与数据目录都依赖它）。

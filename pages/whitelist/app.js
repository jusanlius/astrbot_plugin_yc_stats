/**
 * 验车记录统计 —— 插件 Pages 前端逻辑。
 *
 * 页面运行在 Dashboard 的受限 iframe 中，只能通过 window.AstrBotPluginPage
 * bridge 调用插件后端（main.py 里 register_web_api 注册的路由）。
 */

const bridge = window.AstrBotPluginPage;
const $ = (id) => document.getElementById(id);

const state = {
  today: "",
  days: [],
  groups: [],
  whitelist: [],
  settings: {},
  dataDir: "",
  selectedGroup: "",
};

/** 显示一条操作结果提示。 */
function hint(id, text, kind = "ok") {
  const el = $(id);
  el.textContent = text;
  el.className = `hint ${kind === "err" ? "err" : "ok"}`;
  if (kind !== "err") {
    window.setTimeout(() => {
      if (el.textContent === text) el.textContent = "";
    }, 4000);
  }
}

/** 读取当前设置表单的值。 */
function readSettingsForm() {
  return {
    enabled: $("enabled").checked,
    push_enabled: $("push_enabled").checked,
    reply_receipt: $("reply_receipt").checked,
    block_llm_reply: $("block_llm_reply").checked,
    today_command: $("today_command").checked,
    push_empty_report: $("push_empty_report").checked,
    push_time: $("push_time").value.trim(),
    push_top_n: Number($("push_top_n").value),
    push_min_count: Number($("push_min_count").value),
    name_max_len: Number($("name_max_len").value),
    render_mode: $("render_mode").value,
    image_title: $("image_title").value.trim(),
  };
}

/** 把后端设置回填到表单。 */
function fillSettingsForm(settings) {
  $("enabled").checked = Boolean(settings.enabled);
  $("push_enabled").checked = Boolean(settings.push_enabled);
  $("reply_receipt").checked = Boolean(settings.reply_receipt);
  $("block_llm_reply").checked = Boolean(settings.block_llm_reply);
  $("today_command").checked = Boolean(settings.today_command);
  $("push_empty_report").checked = Boolean(settings.push_empty_report);
  $("push_time").value = settings.push_time || "23:00";
  $("push_top_n").value = settings.push_top_n ?? 15;
  $("push_min_count").value = settings.push_min_count ?? 1;
  $("name_max_len").value = settings.name_max_len ?? 20;
  $("render_mode").value = settings.render_mode || "auto";
  $("image_title").value = settings.image_title || "今日验车战报";
  $("background_enabled").checked = Boolean(settings.background_enabled);
  $("background_path").value = settings.background_path || "";
  $("background_blur").value = settings.background_blur ?? 6;
  $("background_dim").value = settings.background_dim ?? 14;
  syncRangeLabels();
  $("bg-hint").textContent = settings.background_source
    ? `当前背景图：${settings.background_source}`
    : "未找到背景图：把图片放进插件数据目录或 resources/ 即可";
}

/** 同步滑块数值显示。 */
function syncRangeLabels() {
  $("bg-blur-value").textContent = $("background_blur").value;
  $("bg-dim-value").textContent = $("background_dim").value;
}

/** 渲染顶部状态胶囊。 */
function renderBadges() {
  const s = state.settings;
  $("pill-today").textContent = `今天 ${state.today}`;
  if (!s.enabled) {
    $("pill-push").textContent = "记录已停用";
  } else if (!s.push_enabled) {
    $("pill-push").textContent = "定时推送已关闭";
  } else {
    $("pill-push").textContent = `每天 ${s.push_time} 推送`;
  }
}

/** 渲染群白名单表格。 */
function renderGroups() {
  const keyword = $("filter").value.trim().toLowerCase();
  const list = $("group-list");
  list.textContent = "";
  const rows = state.groups.filter((item) => {
    if (!keyword) return true;
    return (
      String(item.group_id).toLowerCase().includes(keyword) ||
      String(item.group_name || "").toLowerCase().includes(keyword)
    );
  });
  if (!rows.length) {
    const empty = document.createElement("div");
    empty.className = "empty-row";
    empty.textContent = state.groups.length
      ? "没有匹配的群"
      : "暂未发现群：让机器人在群里收到一次 #验车 消息后即可自动出现，也可以手动添加群号。";
    list.appendChild(empty);
    return;
  }
  for (const item of rows) {
    const row = document.createElement("div");
    row.className = "tbody-row";

    const check = document.createElement("input");
    check.type = "checkbox";
    check.checked = state.whitelist.includes(item.group_id);
    check.dataset.groupId = item.group_id;
    check.className = "wl-check";

    const gid = document.createElement("span");
    gid.textContent = item.group_id;

    const name = document.createElement("span");
    name.className = "name-cell";
    name.textContent = item.group_name || "—";
    name.title = item.group_name || "";

    const stats = document.createElement("span");
    stats.textContent = item.today_total
      ? `${item.today_total} 次 / ${item.today_unique} 条`
      : "—";

    const source = document.createElement("span");
    source.textContent =
      item.source === "live" ? "机器人所在" : item.source === "manual" ? "手动添加" : "有记录";

    row.append(check, gid, name, stats, source);
    list.appendChild(row);
  }
}

/** 渲染日期 / 群下拉框。 */
function renderSelectors() {
  const days = state.days.length ? state.days : [state.today];
  const dateSel = $("preview-date");
  const keepDate = dateSel.value;
  dateSel.textContent = "";
  for (const day of days) {
    const option = document.createElement("option");
    option.value = day;
    option.textContent = day;
    dateSel.appendChild(option);
  }
  dateSel.value = days.includes(keepDate) ? keepDate : days[0];

  const groupSel = $("preview-group");
  const keepGroup = groupSel.value;
  groupSel.textContent = "";
  const candidates = state.groups.length
    ? state.groups
    : state.whitelist.map((gid) => ({ group_id: gid, group_name: "" }));
  for (const item of candidates) {
    const option = document.createElement("option");
    option.value = item.group_id;
    option.textContent = item.group_name ? `${item.group_name}（${item.group_id}）` : item.group_id;
    groupSel.appendChild(option);
  }
  if (keepGroup) groupSel.value = keepGroup;
  state.selectedGroup = groupSel.value || "";
}

/** 渲染某天的明细表格。 */
function renderDetail(entries) {
  const body = $("detail-body");
  body.textContent = "";
  if (!entries.length) {
    const empty = document.createElement("div");
    empty.className = "empty-row";
    empty.textContent = "该日期没有记录";
    body.appendChild(empty);
    return;
  }
  for (const item of entries.slice(0, 50)) {
    const row = document.createElement("div");
    row.className = "tbody-row";

    const name = document.createElement("span");
    name.className = "name-cell";
    name.textContent = item.name || "未命名";
    name.title = item.link || item.name || "";

    const count = document.createElement("span");
    count.textContent = `${item.count} 次`;

    const users = document.createElement("span");
    users.textContent = `${item.user_count} 人`;

    row.append(name, count, users);
    body.appendChild(row);
  }
}

/** 渲染「群友榜」：谁发送 #验车 最多。 */
function renderSenders(senders, senderTotal) {
  const body = $("senders-body");
  body.textContent = "";
  $("senders-total").textContent = senders.length
    ? `共 ${senderTotal ?? senders.length} 位群友参与`
    : "";
  if (!senders.length) {
    const empty = document.createElement("span");
    empty.className = "hint";
    empty.textContent = "该日期没有群友记录";
    body.appendChild(empty);
    return;
  }
  for (const sender of senders.slice(0, 30)) {
    const chip = document.createElement("span");
    chip.className = `sender-chip ${sender.rank <= 3 ? `s${sender.rank}` : ""}`;

    const rank = document.createElement("span");
    rank.className = "s-rank";
    rank.textContent = String(sender.rank);

    const name = document.createElement("span");
    name.className = "s-name";
    name.textContent = sender.name || `用户${String(sender.uid).slice(-4)}`;
    name.title = sender.uid ? `QQ/ID: ${sender.uid}` : "";

    const count = document.createElement("span");
    count.className = "s-count";
    count.textContent = `${sender.count} 次`;

    chip.append(rank, name, count);
    body.appendChild(chip);
  }
}

/** 拉取某天 / 某群明细并渲染。 */
async function loadDetail() {
  const date = $("preview-date").value || state.today;
  const groupId = $("preview-group").value || "";
  const params = { date };
  if (groupId) params.group_id = groupId;
  try {
    const data = await bridge.apiGet("stats", params);
    renderDetail(data.entries || []);
    renderSenders(data.senders || [], data.sender_total);
  } catch (error) {
    hint("push-result", `明细加载失败：${error.message}`, "err");
  }
}

/** 加载插件概览数据并整体渲染。 */
async function loadOverview(keepHints = false) {
  const data = await bridge.apiGet("overview");
  state.today = data.today;
  state.days = data.days || [];
  state.groups = data.groups || [];
  state.whitelist = data.whitelist || [];
  state.settings = data.settings || {};
  state.dataDir = data.data_dir || "";
  fillSettingsForm(state.settings);
  renderBadges();
  renderGroups();
  renderSelectors();
  $("foot").textContent = `数据目录：${state.dataDir} · 触发词：${(state.settings.triggers || []).join(" / ")}`;
  if (!keepHints) hint("settings-hint", "");
  await loadDetail();
}

/** 绑定页面事件。 */
function bindEvents() {
  $("filter").addEventListener("input", renderGroups);
  $("preview-group").addEventListener("change", loadDetail);
  $("preview-date").addEventListener("change", loadDetail);

  $("btn-reload").addEventListener("click", async () => {
    await loadOverview();
    hint("settings-hint", "已重新载入");
  });

  $("btn-save-settings").addEventListener("click", async () => {
    try {
      await bridge.apiPost("settings", readSettingsForm());
      hint("settings-hint", "设置已保存");
      await loadOverview(true);
    } catch (error) {
      hint("settings-hint", `保存失败：${error.message}`, "err");
    }
  });

  $("background_blur").addEventListener("input", syncRangeLabels);
  $("background_dim").addEventListener("input", syncRangeLabels);

  $("btn-save-background").addEventListener("click", async () => {
    try {
      await bridge.apiPost("settings", {
        background_enabled: $("background_enabled").checked,
        background_blur: Number($("background_blur").value),
        background_dim: Number($("background_dim").value),
        background_path: $("background_path").value.trim(),
      });
      hint("bg-hint", "背景设置已保存，正在刷新预览…");
      await loadOverview(true);
      await applyBackground();
      hint("bg-hint", "已应用新的毛玻璃效果");
    } catch (error) {
      hint("bg-hint", `保存失败：${error.message}`, "err");
    }
  });

  $("btn-reset-background").addEventListener("click", async () => {
    $("background_blur").value = 6;
    $("background_dim").value = 14;
    $("background_enabled").checked = true;
    syncRangeLabels();
    try {
      await bridge.apiPost("settings", {
        background_enabled: true,
        background_blur: 6,
        background_dim: 14,
      });
      await loadOverview(true);
      await applyBackground();
      hint("bg-hint", "已恢复默认（模糊 6 / 雾化 14）");
    } catch (error) {
      hint("bg-hint", `恢复失败：${error.message}`, "err");
    }
  });

  $("btn-add-group").addEventListener("click", () => {
    const value = $("manual-group").value.trim();
    if (!value) return;
    if (!state.groups.some((item) => item.group_id === value)) {
      state.groups.unshift({ group_id: value, group_name: "", source: "manual", today_total: 0, today_unique: 0 });
    }
    if (!state.whitelist.includes(value)) state.whitelist.push(value);
    $("manual-group").value = "";
    renderGroups();
    renderSelectors();
    hint("whitelist-hint", `已加入待保存列表：${value}`);
  });

  $("btn-select-all").addEventListener("click", () => {
    for (const box of document.querySelectorAll(".wl-check")) {
      box.checked = true;
    }
  });

  $("btn-clear").addEventListener("click", () => {
    for (const box of document.querySelectorAll(".wl-check")) {
      box.checked = false;
    }
  });

  $("btn-save-whitelist").addEventListener("click", async () => {
    const groups = [...document.querySelectorAll(".wl-check")]
      .filter((box) => box.checked)
      .map((box) => box.dataset.groupId);
    for (const gid of state.whitelist) {
      if (!groups.includes(gid)) groups.push(gid);
    }
    if (!groups.length) {
      // 一个都不勾选 = 不限制
      const confirmed = window.confirm("没有勾选任何群，将保存为空白名单（= 不限制，记录并推送所有群）。确定吗？");
      if (!confirmed) return;
    }
    try {
      const saved = await bridge.apiPost("whitelist", { groups: [...new Set(groups)] });
      state.whitelist = saved.whitelist || [];
      hint("whitelist-hint", state.whitelist.length ? `已保存 ${state.whitelist.length} 个群` : "已保存：不限制所有群");
      await loadOverview(true);
    } catch (error) {
      hint("whitelist-hint", `保存失败：${error.message}`, "err");
    }
  });

  $("btn-preview").addEventListener("click", async () => {
    try {
      const payload = { date: $("preview-date").value || state.today };
      if ($("preview-group").value) payload.group_id = $("preview-group").value;
      const data = await bridge.apiPost("preview", payload);
      $("preview-img").src = data.image;
      $("preview-img").hidden = false;
      $("preview-empty").hidden = true;
      hint("push-result", `已生成 ${data.date} 预览（${data.total_count} 次 / ${data.unique_count} 条）`);
    } catch (error) {
      hint("push-result", `预览失败：${error.message}`, "err");
    }
  });

  $("btn-push").addEventListener("click", async () => {
    const payload = { date: $("preview-date").value || state.today };
    const groupId = $("preview-group").value;
    if (groupId) payload.groups = [groupId];
    const confirmed = window.confirm(`确定立刻把 ${payload.date} 的战报推送到群吗？`);
    if (!confirmed) return;
    try {
      const data = await bridge.apiPost("push", payload);
      const ok = (data.results || []).filter((item) => item.ok).length;
      const failed = (data.results || []).filter((item) => !item.ok);
      const detail = failed.length
        ? `，失败 ${failed.length} 个（${failed.map((item) => `${item.group_id}:${item.error}`).join("；")}）`
        : "";
      hint("push-result", `推送完成：成功 ${ok} 个${detail}`, failed.length ? "err" : "ok");
      await loadOverview(true);
    } catch (error) {
      hint("push-result", `推送失败：${error.message}`, "err");
    }
  });
}

/** 拉取背景图并应用「背景图 + 毛玻璃」外观。 */
async function applyBackground() {
  try {
    const data = await bridge.apiGet("background");
    if (!data || !data.image) {
      document.documentElement.classList.remove("bg-on");
      return;
    }
    const isDark = Boolean(bridge.getContext()?.isDark);
    const blur = Math.max(6, Number(data.blur) || 6);
    const alpha = Math.min(0.78, Math.max(0.14, 0.08 + (Number(data.dim) || 14) / 200));

    const bg = $("bg");
    bg.style.backgroundImage = `url("${data.image}")`;
    bg.style.filter = `blur(${blur}px) saturate(1.08)`;

    const frost = $("bg-frost");
    frost.style.background = isDark
      ? `linear-gradient(165deg, rgba(10, 12, 20, ${Math.min(0.9, alpha + 0.15)}), rgba(18, 18, 26, ${Math.min(0.9, alpha + 0.08)}) 45%, rgba(26, 16, 26, ${Math.min(0.9, alpha + 0.15)}))`
      : `linear-gradient(165deg, rgba(236, 244, 255, ${alpha}), rgba(255, 255, 255, ${alpha}) 45%, rgba(255, 236, 246, ${alpha}))`;

    document.documentElement.classList.add("bg-on");
  } catch (error) {
    console.warn("背景图加载失败：", error.message);
  }
}

/** 页面入口。 */
async function boot() {
  try {
    const context = await bridge.ready();
    if (context && context.locale) document.documentElement.lang = context.locale;
    if (context && context.i18n && context.i18n.pages) {
      const page = context.i18n.pages.whitelist;
      if (page && page.title) {
        $("page-title").textContent = page.title;
        document.title = page.title;
      }
    }
    $("app").hidden = false;
    bindEvents();
    await loadOverview();
    await applyBackground();
    // 跟随 WebUI 主题/语言切换重新应用毛玻璃配色
    bridge.onContext(() => {
      applyBackground();
    });
  } catch (error) {
    document.body.innerHTML = `<p style="padding:24px;font-family:sans-serif">插件页面加载失败：${error.message}</p>`;
  }
}

boot();

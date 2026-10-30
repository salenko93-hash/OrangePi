(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const keyInput = $("adminKey");
  const workspace = $("workspace");
  const tabs = $("tabs");
  const authState = $("authState");
  const toast = $("toast");
  let dashboard = null;
  let xlsxToken = "";
  let xlsxPreviewData = null;

  keyInput.value = "";
  const key = () => keyInput.value.trim();
  function localDateISO() {
    const d = new Date();
    d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
    return d.toISOString().slice(0, 10);
  }

  function esc(v) {
    return String(v ?? "").replace(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[c],
    );
  }
  function notify(message, type = "ok") {
    toast.textContent = message;
    toast.className = `toast ${type}`;
    clearTimeout(notify._t);
    notify._t = setTimeout(() => toast.classList.add("hidden"), 3600);
  }
  async function api(path, opt = {}) {
    const headers = {
      "Content-Type": "application/json",
      ...(opt.headers || {}),
    };
    const r = await fetch(path, { ...opt, headers, cache: "no-store" });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
    return data;
  }
  function fmtBytes(n) {
    n = Number(n) || 0;
    const u = ["B", "KB", "MB", "GB", "TB"];
    let i = 0;
    while (n >= 1024 && i < u.length - 1) {
      n /= 1024;
      i++;
    }
    return `${n.toFixed(i ? 1 : 0)} ${u[i]}`;
  }
  function fmtUptime(s) {
    s = Math.max(0, Number(s) || 0);
    const d = Math.floor(s / 86400),
      h = Math.floor((s % 86400) / 3600),
      m = Math.floor((s % 3600) / 60);
    return `${d ? d + " д " : ""}${h} г ${m} хв`;
  }
  function fmtTime(ts) {
    if (!ts) return "—";
    const d = new Date(Number(ts) * 1000);
    return isNaN(d) ? String(ts) : d.toLocaleString("uk-UA");
  }
  function setField(form, name, value) {
    const el = form?.elements?.[name];
    if (!el) return;
    if (el.type === "checkbox") el.checked = !!value;
    else el.value = value ?? "";
    if (el.type === "range") updateOutput(el);
  }
  function hydrateForm(form, cfg) {
    if (!form) return;
    for (const el of form.elements) {
      if (el.name && Object.prototype.hasOwnProperty.call(cfg, el.name))
        setField(form, el.name, cfg[el.name]);
    }
  }
  function collectForm(form) {
    const out = {};
    for (const el of form.elements) {
      if (!el.name) continue;
      if (el.type === "checkbox") out[el.name] = el.checked;
      else if (el.type === "number" || el.type === "range")
        out[el.name] = el.value === "" ? "" : Number(el.value);
      else out[el.name] = el.value;
    }
    return out;
  }
  function updateOutput(el) {
    const o = document.querySelector(`output[data-for="${el.name}"]`);
    if (o) o.textContent = `${el.value}%`;
  }
  document
    .querySelectorAll("input[type=range]")
    .forEach((r) => r.addEventListener("input", () => updateOutput(r)));

  function activateTab(name) {
    document
      .querySelectorAll(".tabs button[data-tab]")
      .forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
    document
      .querySelectorAll(".tab-page")
      .forEach((p) => p.classList.toggle("active", p.id === `tab-${name}`));
    if (name === "demo") {
      const preview = document.getElementById("demoPreview");
      if (preview && !preview.getAttribute("src"))
        preview.setAttribute("src", preview.dataset.src);
    }
    localStorage.setItem("lyceumtv.adminTab", name);
  }
  tabs.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-tab]");
    if (b) activateTab(b.dataset.tab);
  });

  function statusTile(label, value, cls = "") {
    return `<div class="status-tile ${cls}"><b>${esc(label)}</b><strong>${esc(value)}</strong></div>`;
  }
  function renderStatus(d) {
    const s = d.state || {},
      a = s.alarm || {},
      w = s.weather || {},
      sy = s.sync || {},
      sys = d.system || {};
    $("statusGrid").innerHTML = [
      statusTile(
        "Режим",
        s.mode || "—",
        s.mode === "AIR_RAID" ? "bad" : "good",
      ),
      statusTile("Час", s.clock || "—"),
      statusTile(
        "Тривога",
        a.active ? "АКТИВНА" : "немає",
        a.active ? "bad" : "good",
      ),
      statusTile(
        "Синхронізація",
        sy.ok === false ? "ПОМИЛКА" : sy.version || "готово",
        sy.ok === false ? "bad" : "good",
      ),
      statusTile(
        "Погода",
        w.available
          ? `${w.temperature >= 0 ? "+" : ""}${w.temperature}° ${w.condition || ""}`
          : "немає даних",
        w.available ? "good" : "warn",
      ),
      statusTile(
        "Екрани",
        `${d.smart_campus?.screens_online || 0}/${d.smart_campus?.screens_total || 0} ONLINE`,
        (d.smart_campus?.screens_online || 0) ===
          (d.smart_campus?.screens_total || 0)
          ? "good"
          : "warn",
      ),
      statusTile("Версія", s.app?.version || d.config?.version || "—"),
    ].join("");

    const mem = sys.memory || {},
      disk = sys.disk || {},
      services = sys.services || {};
    $("systemGrid").innerHTML = [
      ["Hostname", sys.hostname || "—"],
      ["IP", (sys.ips || []).join(", ") || "—"],
      ["Uptime", fmtUptime(sys.uptime_seconds)],
      ["CPU", sys.cpu_temp_c == null ? "—" : `${sys.cpu_temp_c} °C`],
      ["RAM", `${fmtBytes(mem.used)} / ${fmtBytes(mem.total)}`],
      ["Диск", `${fmtBytes(disk.used)} / ${fmtBytes(disk.total)}`],
      ["LyceumTV", services.lyceumtv || "—"],
      ["Kiosk", services.kiosk || "—"],
      ["Watchdog", services.watchdog || "—"],
      ["Load", (sys.load || []).join(" / ") || "—"],
    ]
      .map(([k, v]) => `<div><b>${esc(k)}</b><strong>${esc(v)}</strong></div>`)
      .join("");
  }
  function logClass(kind) {
    kind = String(kind || "");
    if (kind.includes("error")) return "error";
    if (kind.includes("alarm")) return "alarm";
    return "";
  }
  function renderLogs(logs) {
    const html =
      (logs || [])
        .map(
          (x) => `<div class="log-item ${logClass(x.kind)}">
    <div class="log-head"><span>${esc(x.kind || "event")} • ${esc(x.actor || "system")}</span><span>${esc(x.at || "")}</span></div>
    <div class="log-msg">${esc(x.message || "")}</div>
  </div>`,
        )
        .join("") || `<div class="hint">Журнал порожній</div>`;
    $("logList").innerHTML = html;
    $("recentLogs").innerHTML =
      (logs || [])
        .slice(0, 8)
        .map(
          (x) => `<div class="log-item ${logClass(x.kind)}">
    <div class="log-head"><span>${esc(x.kind || "event")}</span><span>${esc(x.at || "")}</span></div>
    <div class="log-msg">${esc(x.message || "")}</div>
  </div>`,
        )
        .join("") || `<div class="hint">Журнал порожній</div>`;
  }
  function badge(active, text) {
    return `<span class="badge ${active ? "" : "off"}">${esc(text)}</span>`;
  }
  function renderSubstitutions(items) {
    $("subList").innerHTML =
      (items || [])
        .slice()
        .sort((a, b) =>
          String(b.date || "").localeCompare(String(a.date || "")),
        )
        .map((x) => {
          const entries = (x.entries || [])
            .map(
              (e) =>
                `${e.subgroup ? e.subgroup + " " : ""}${e.subject || "—"} • ${e.room || "—"} • ${e.teacher || "—"}`,
            )
            .join(" / ");
          return `<div class="data-row">
      <div><div class="title">${badge(x.active !== false, x.active === false ? "ВИМКНЕНО" : "АКТИВНА")} ${esc(x.date || "ALL")} • ${esc(x.class)} • ${esc(x.lesson)} урок</div>
      <div class="meta">${esc(entries)}${x.note ? `<br>${esc(x.note)}` : ""}</div></div>
      <div class="row-actions"><button data-edit-sub="${esc(x.id)}">РЕДАГУВАТИ</button><button class="danger" data-del-kind="substitution" data-del-id="${esc(x.id)}">ВИДАЛИТИ</button></div>
    </div>`;
        })
        .join("") || `<div class="hint">Локальних замін немає.</div>`;
  }
  function renderAnnouncements(items) {
    $("announcementList").innerHTML =
      (items || [])
        .map(
          (x) => `<div class="data-row">
    <div><div class="title">${badge(x.active !== false, x.active === false ? "ВИМКНЕНО" : "АКТИВНЕ")} <span class="badge priority">P${esc(x.priority ?? 5)}</span> ${esc(x.title || x.message || "Оголошення")}</div>
    <div class="meta">${esc(x.message || "")}${x.valid_from || x.valid_to ? `<br>${esc(x.valid_from || "…")} → ${esc(x.valid_to || "…")}` : ""}</div></div>
    <div class="row-actions"><button data-edit-ann="${esc(x.id)}">РЕДАГУВАТИ</button><button class="danger" data-del-kind="announcement" data-del-id="${esc(x.id)}">ВИДАЛИТИ</button></div>
  </div>`,
        )
        .join("") || `<div class="hint">Оголошень немає.</div>`;
  }
  function renderEvents(items) {
    $("eventList").innerHTML =
      (items || [])
        .map(
          (x) => `<div class="data-row">
    <div><div class="title">${badge(x.active !== false, x.active === false ? "ВИМКНЕНО" : "АКТИВНА")} ${esc(x.title || "Подія")}</div>
    <div class="meta">${esc(x.date || "без дати")} ${esc(x.start_time || "")} ${x.end_time ? `– ${esc(x.end_time)}` : ""}${x.message ? `<br>${esc(x.message)}` : ""}</div></div>
    <div class="row-actions"><button data-edit-event="${esc(x.id)}">РЕДАГУВАТИ</button><button class="danger" data-del-kind="event" data-del-id="${esc(x.id)}">ВИДАЛИТИ</button></div>
  </div>`,
        )
        .join("") || `<div class="hint">Подій немає.</div>`;
  }
  function renderCalendar(cal) {
    const rows = [];
    for (const x of cal?.daysOff || [])
      rows.push(
        `<div class="data-row"><div><div class="title">ДЕНЬ • ${esc(x.date)}</div><div class="meta">${esc(x.label || "Вихідний")}</div></div><div class="row-actions"><button class="danger" data-cal-kind="daysOff" data-cal-id="${esc(x.id)}">ВИДАЛИТИ</button></div></div>`,
      );
    for (const x of cal?.ranges || [])
      rows.push(
        `<div class="data-row"><div><div class="title">ПЕРІОД • ${esc(x.from)} → ${esc(x.to)}</div><div class="meta">${esc(x.label || "Канікули")}</div></div><div class="row-actions"><button class="danger" data-cal-kind="ranges" data-cal-id="${esc(x.id)}">ВИДАЛИТИ</button></div></div>`,
      );
    $("calendarList").innerHTML =
      rows.join("") ||
      `<div class="hint">Локальних календарних винятків немає.</div>`;
  }
  function renderBells(bells) {
    const arr =
      bells && bells.length
        ? bells
        : Array.from({ length: 8 }, (_, i) => ({
            lesson: i + 1,
            start: "",
            end: "",
          }));
    $("bellsEditor").innerHTML = arr
      .map(
        (x) => `<div class="bell-row" data-lesson="${Number(x.lesson) || 0}">
    <strong>${Number(x.lesson) || "?"}</strong>
    <label>Початок <input type="time" data-bell-start value="${esc(x.start || "")}"></label>
    <label>Кінець <input type="time" data-bell-end value="${esc(x.end || "")}"></label>
  </div>`,
      )
      .join("");
  }
  function renderBackups(items) {
    $("backupList").innerHTML =
      (items || [])
        .map(
          (x) => `<div class="data-row">
    <div><div class="title">${esc(x.name)}</div><div class="meta">${fmtBytes(x.size)} • ${fmtTime(x.mtime)}</div></div>
    <div class="row-actions"><button class="good" data-restore="${esc(x.name)}">ВІДНОВИТИ</button><button class="danger" data-backup-delete="${esc(x.name)}">ВИДАЛИТИ</button></div>
  </div>`,
        )
        .join("") || `<div class="hint">Backup ще не створювалися.</div>`;
  }

  function renderScreens(items) {
    const arr = items || [];
    $("screenCount").textContent =
      `${arr.filter((x) => x.online).length}/${arr.length} ONLINE`;
    $("screenList").innerHTML =
      arr
        .map(
          (x) => `<div class="screen-row ${x.online ? "" : "offline"}">
    <div><div class="screen-name">${esc(x.name || x.id)}</div><div class="screen-meta">${esc(x.id)} • ${esc(x.ip || "IP —")}</div></div>
    <div><div class="screen-state ${x.online ? "online" : "offline"}">${x.online ? "ONLINE" : "OFFLINE"}</div><div class="screen-meta">${x.age_seconds == null ? "ще не підключався" : `${x.age_seconds} с тому`}</div></div>
    <div><span class="badge">${esc(x.profile || "schedule")}</span><div class="screen-meta">v${esc(x.version || "—")}</div></div>
    <div class="screen-meta">${esc(x.building || "")} ${x.floor ? `• ${esc(x.floor)} пов.` : ""} ${x.zone ? `• ${esc(x.zone)}` : ""}<br>${esc((x.user_agent || "").slice(0, 95))}</div>
    <div class="row-actions">
      <button data-screen-edit="${esc(x.id)}">ПРОФІЛЬ</button>
      <button data-screen-command="reload" data-screen-id="${esc(x.id)}" class="secondary">RELOAD</button>
      <button data-screen-command="restart" data-screen-id="${esc(x.id)}" class="secondary">RESTART</button>
      <button data-screen-pair="${esc(x.id)}" class="secondary">ПІДКЛЮЧИТИ</button>
      <button data-screen-delete="${esc(x.id)}" class="danger">ВИДАЛИТИ</button>
    </div>
  </div>`,
        )
        .join("") ||
      `<div class="hint">Екрани ще не зареєстровані. Відкрийте TV з параметром <code>?screen=hall-main</code>.</div>`;
  }
  function configuredMobileUrl(cfg = dashboard?.config || {}) {
    let raw = String(cfg.mobile_public_url || "").trim();
    if (!raw) raw = new URL("/mobile/", window.location.href).toString();
    try {
      const u = new URL(raw);
      if (!u.pathname || u.pathname === "/") u.pathname = "/mobile/";
      if (!u.pathname.endsWith("/")) u.pathname += "/";
      u.search = "";
      u.hash = "";
      return u.toString();
    } catch (_) {
      return new URL("/mobile/", window.location.href).toString();
    }
  }
  function mobileClassUrl() {
    const cls = $("mobileQrClass")?.value || "10-А";
    const u = new URL(configuredMobileUrl());
    u.searchParams.set("class", cls);
    return u.toString();
  }
  function renderMobileClassQr() {
    const url = mobileClassUrl();
    if ($("mobileClassUrl")) $("mobileClassUrl").value = url;
    if ($("openMobileClass")) $("openMobileClass").href = url;
    if ($("mobileQr"))
      $("mobileQr").src = `/api/qr.svg?text=${encodeURIComponent(url)}`;
  }
  function renderMobile(cfg) {
    const url = configuredMobileUrl(cfg);
    $("mobileUrl").value = url;
    $("openMobile").href = url;
    renderMobileClassQr();
  }

  function renderTelegramDiag(tg) {
    const el = $("telegramDiag");
    if (!el) return;
    tg = tg || {};
    const yes = (v) => (v ? "ТАК" : "НІ");
    const state = !tg.enabled
      ? "MONITORING ВИМКНЕНО"
      : !tg.configured
        ? "НЕ НАЛАШТОВАНО"
        : !tg.commands_enabled
          ? "КОМАНДИ ВИМКНЕНІ"
          : tg.last_error
            ? "ПОМИЛКА"
            : tg.polling
              ? "POLLING ONLINE"
              : tg.prepared
                ? "ГОТОВО"
                : "ПІДКЛЮЧЕННЯ…";
    el.textContent = [
      `Стан: ${state}`,
      `Bot: ${tg.bot_username ? "@" + tg.bot_username : "—"}`,
      `Thread: ${yes(tg.thread_alive)} • Prepared: ${yes(tg.prepared)} • Polling: ${yes(tg.polling)}`,
      `Останній poll: ${tg.last_poll_at || "—"}`,
      `Остання команда: ${tg.last_command || "—"} ${tg.last_command_at || ""}`,
      `Offset: ${tg.offset ?? 0}`,
      tg.last_error ? `Помилка: ${tg.last_error}` : "Помилка: немає",
    ].join("\n");
    el.classList.toggle("error", !!tg.last_error);
  }
  function renderXlsxPreview(d) {
    const p = d?.preview || {};
    xlsxPreviewData = p;
    const ok = !(p.errors || []).length;
    $("xlsxSummary").textContent = [
      `Файл: ${p.file_name || "—"}`,
      `Аркуш: ${p.sheet || "—"}`,
      `Записів: ${p.entry_count || 0}`,
      `Класів: ${(p.classes || []).join(", ") || "—"}`,
      `SHA-256: ${p.sha256 || "—"}`,
    ].join("\n");
    const issues = [
      ...(p.errors || []).map((x) => ({ type: "error", text: x })),
      ...(p.warnings || []).map((x) => ({ type: "warning", text: x })),
    ];
    $("xlsxIssues").innerHTML =
      issues
        .map(
          (x) =>
            `<div class="data-row issue ${x.type === "error" ? "error" : ""}"><div><div class="title">${x.type === "error" ? "ПОМИЛКА" : "ПОПЕРЕДЖЕННЯ"}</div><div class="meta">${esc(x.text)}</div></div></div>`,
        )
        .join("") ||
      (ok
        ? `<div class="data-row"><div><div class="title ok">VALIDATION OK</div><div class="meta">Критичних помилок не знайдено.</div></div></div>`
        : "");
    $("xlsxSamples").innerHTML = (p.samples || [])
      .map((x) => {
        const entries = (x.entries || [])
          .map(
            (e) =>
              `${e.subject || "—"} • ${e.room || "—"} • ${e.teacher || "—"}`,
          )
          .join("<br>");
        return `<div class="import-sample"><strong>${esc(x.day)}</strong><strong>${esc(x.class)}</strong><strong>${esc(x.lesson)} ур.</strong><div class="sample-entries">${entries}</div></div>`;
      })
      .join("");
    if (p.suggested_target) $("xlsxTarget").value = p.suggested_target;
    $("xlsxApply").disabled = !xlsxToken || !ok;
  }
  function fileAsBase64(file) {
    return new Promise((resolve, reject) => {
      const r = new FileReader();
      r.onload = () => {
        const s = String(r.result || "");
        resolve(s.includes(",") ? s.split(",", 2)[1] : s);
      };
      r.onerror = () =>
        reject(r.error || new Error("Не вдалося прочитати файл"));
      r.readAsDataURL(file);
    });
  }
  function hydrateSettings(cfg) {
    [
      "scheduleSettings",
      "slideshowSettings",
      "syncSettings",
      "alarmSettings",
      "weatherSettings",
      "silenceSettings",
      "otaSettings",
      "accessSettings",
      "mobileSettings",
      "telegramSettings",
      "smartOpsSettings",
    ].forEach((id) => hydrateForm($(id), cfg));
    updateTickerPreview();
  }
  function renderAll(d, hydrate = true) {
    dashboard = d;
    renderStatus(d);
    renderLogs(d.logs || []);
    renderTelegramDiag(d.telegram || {});
    if (hydrate) {
      hydrateSettings(d.config || {});
      renderSubstitutions(d.control?.substitutions || []);
      renderAnnouncements(d.control?.announcements || []);
      renderEvents(d.control?.events || []);
      renderCalendar(d.calendar || {});
      renderBells(d.bells || []);
      renderBackups(d.backups || []);
      if (d.update?.pending || d.update?.last || d.update?.error)
        $("otaState").textContent = JSON.stringify(d.update, null, 2);
      renderScreens(d.screens || []);
      renderMobile(d.config || {});
    } else {
      renderScreens(d.screens || []);
    }
  }
  async function refreshDashboard(hydrate = false) {
    const d = await api("/api/admin/dashboard");
    renderAll(d, hydrate);
    return d;
  }
  async function connect() {
    authState.textContent = "Підключення…";
    try {
      await window.LyceumAuth.login(key());
      keyInput.value = "";
      const d = await refreshDashboard(true);
      workspace.classList.remove("disabled");
      tabs.classList.remove("disabled");
      authState.textContent = "Підключено";
      authState.className = "ok";
      activateTab(localStorage.getItem("lyceumtv.adminTab") || "dashboard");
    } catch (e) {
      workspace.classList.add("disabled");
      tabs.classList.add("disabled");
      authState.textContent = e.message;
      authState.className = "err";
    }
  }
  $("connect").onclick = connect;
  $("refreshAll").onclick = () =>
    refreshDashboard(true)
      .then(() => notify("Стан оновлено"))
      .catch((e) => notify(e.message, "err"));

  async function saveSettings(form) {
    const cfg = collectForm(form);
    const newKey = String(cfg.admin_key || "").trim();
    const d = await api("/api/admin/config", {
      method: "POST",
      body: JSON.stringify({ config: cfg }),
    });
    if (newKey) {
      await window.LyceumAuth.login(newKey);
      keyInput.value = "";
      form.elements.admin_key.value = "";
    }
    if (form.elements.telegram_bot_token)
      form.elements.telegram_bot_token.value = "";
    if (form.elements.alerts_token) form.elements.alerts_token.value = "";
    if (form.elements.dispatcher_key) form.elements.dispatcher_key.value = "";
    if (form.elements.teacher_key) form.elements.teacher_key.value = "";
    if (form.elements.cloud_mirror_token)
      form.elements.cloud_mirror_token.value = "";
    notify(d.message || "Збережено");
    if (form.id === "mobileSettings") {
      dashboard = dashboard || {};
      dashboard.config = { ...(dashboard.config || {}), ...cfg };
      renderMobile(dashboard.config);
    }
    if (form.id === "telegramSettings") {
      try {
        const tg = await api("/api/admin/action", {
          method: "POST",
          body: JSON.stringify({ action: "telegram_reconnect" }),
        });
        if (tg?.telegram) renderTelegramDiag(tg.telegram);
        if (tg?.ok === false)
          notify(tg.message || "Telegram reconnect error", "err");
      } catch (_) {}
    }
    await refreshDashboard(false);
  }
  document.querySelectorAll(".settings-form").forEach((form) =>
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      saveSettings(form).catch((err) => notify(err.message, "err"));
    }),
  );

  document.addEventListener("click", async (e) => {
    const actionBtn = e.target.closest("[data-action]");
    if (actionBtn) {
      actionBtn.disabled = true;
      try {
        const d = await api("/api/admin/action", {
          method: "POST",
          body: JSON.stringify({ action: actionBtn.dataset.action }),
        });
        notify(d.message || "Готово", d.ok === false ? "err" : "ok");
        await refreshDashboard(false);
      } catch (err) {
        notify(err.message, "err");
      } finally {
        actionBtn.disabled = false;
      }
      return;
    }
    const del = e.target.closest("[data-del-kind]");
    if (del) {
      if (!confirm("Видалити запис?")) return;
      try {
        await api("/api/admin/item", {
          method: "POST",
          body: JSON.stringify({
            op: "delete",
            kind: del.dataset.delKind,
            id: del.dataset.delId,
          }),
        });
        notify("Видалено");
        await refreshDashboard(true);
      } catch (err) {
        notify(err.message, "err");
      }
      return;
    }
    const cal = e.target.closest("[data-cal-kind]");
    if (cal) {
      if (!confirm("Видалити календарний запис?")) return;
      try {
        await api("/api/admin/calendar", {
          method: "POST",
          body: JSON.stringify({
            op: "delete",
            kind: cal.dataset.calKind,
            id: cal.dataset.calId,
          }),
        });
        notify("Видалено");
        await refreshDashboard(true);
      } catch (err) {
        notify(err.message, "err");
      }
      return;
    }
    const restore = e.target.closest("[data-restore]");
    if (restore) {
      if (
        !confirm(
          `Відновити ${restore.dataset.restore}? Поточні налаштування та дані буде замінено.`,
        )
      )
        return;
      try {
        const d = await api("/api/admin/action", {
          method: "POST",
          body: JSON.stringify({
            action: "restore_backup",
            name: restore.dataset.restore,
          }),
        });
        notify(d.message || "Backup відновлено");
        await refreshDashboard(true);
      } catch (err) {
        notify(err.message, "err");
      }
      return;
    }
    const bd = e.target.closest("[data-backup-delete]");
    if (bd) {
      if (!confirm("Видалити backup?")) return;
      try {
        await api("/api/admin/action", {
          method: "POST",
          body: JSON.stringify({
            action: "delete_backup",
            name: bd.dataset.backupDelete,
          }),
        });
        notify("Backup видалено");
        await refreshDashboard(true);
      } catch (err) {
        notify(err.message, "err");
      }
      return;
    }
    const editSub = e.target.closest("[data-edit-sub]");
    if (editSub) {
      const x = dashboard?.control?.substitutions?.find(
        (y) => y.id === editSub.dataset.editSub,
      );
      if (x) fillSub(x);
      return;
    }
    const editAnn = e.target.closest("[data-edit-ann]");
    if (editAnn) {
      const x = dashboard?.control?.announcements?.find(
        (y) => y.id === editAnn.dataset.editAnn,
      );
      if (x) fillGeneric($("announcementForm"), x);
      return;
    }
    const editEvent = e.target.closest("[data-edit-event]");
    if (editEvent) {
      const x = dashboard?.control?.events?.find(
        (y) => y.id === editEvent.dataset.editEvent,
      );
      if (x) fillGeneric($("eventForm"), x);
      return;
    }
    const screenPair = e.target.closest("[data-screen-pair]");
    if (screenPair) {
      if (!confirm("Створити новий токен? Попереднє підключення цього екрана втратить доступ до команд.")) return;
      try {
        const result = await api("/api/admin/screen", {
          method: "POST",
          body: JSON.stringify({ op: "pair", id: screenPair.dataset.screenPair }),
        });
        const link = new URL("/", location.origin);
        link.searchParams.set("screen", result.id);
        link.hash = new URLSearchParams({ device: result.token }).toString();
        prompt("Відкрийте це приватне посилання на телевізорі. Воно дозволяє керувати лише цим екраном:", link.href);
      } catch (error) { notify(error.message, "err"); }
      return;
    }
    const screenEdit = e.target.closest("[data-screen-edit]");
    if (screenEdit) {
      const x = dashboard?.screens?.find(
        (y) => y.id === screenEdit.dataset.screenEdit,
      );
      if (x) {
        fillGeneric($("screenForm"), x);
        activateTab("screens");
      }
      return;
    }
    const screenCmd = e.target.closest("[data-screen-command]");
    if (screenCmd) {
      screenCmd.disabled = true;
      try {
        const d = await api("/api/admin/screen", {
          method: "POST",
          body: JSON.stringify({
            op: "command",
            id: screenCmd.dataset.screenId,
            command: screenCmd.dataset.screenCommand,
          }),
        });
        notify(d.message || "Команду надіслано");
        await refreshDashboard(true);
      } catch (err) {
        notify(err.message, "err");
      } finally {
        screenCmd.disabled = false;
      }
      return;
    }
    const screenDel = e.target.closest("[data-screen-delete]");
    if (screenDel) {
      if (!confirm("Видалити екран із Smart Campus?")) return;
      try {
        await api("/api/admin/screen", {
          method: "POST",
          body: JSON.stringify({
            op: "delete",
            id: screenDel.dataset.screenDelete,
          }),
        });
        notify("Екран видалено");
        await refreshDashboard(true);
      } catch (err) {
        notify(err.message, "err");
      }
      return;
    }
  });

  function fillGeneric(form, x) {
    for (const [k, v] of Object.entries(x)) setField(form, k, v);
    form.scrollIntoView({ behavior: "smooth", block: "center" });
  }
  function fillSub(x) {
    const f = $("subForm");
    ["id", "date", "class", "lesson", "scope", "active", "note"].forEach((k) =>
      setField(f, k, x[k]),
    );
    for (let i = 0; i < 2; i++) {
      const e = x.entries?.[i] || {};
      setField(f, `subgroup${i + 1}`, e.subgroup || "");
      setField(f, `subject${i + 1}`, e.subject || "");
      setField(f, `room${i + 1}`, e.room || "");
      setField(f, `teacher${i + 1}`, e.teacher || "");
    }
    f.scrollIntoView({ behavior: "smooth", block: "center" });
  }
  function resetSub() {
    const f = $("subForm");
    f.reset();
    f.elements.id.value = "";
    f.elements.active.checked = true;
    f.elements.date.value = localDateISO();
    f.elements.lesson.value = 1;
    f.elements.scope.value = "both";
  }
  $("subReset").onclick = resetSub;
  function updateTickerPreview() {
    const slider = $("tickerSpeedInput"),
      rail = $("announcementPreviewRail"),
      track = $("announcementPreviewText");
    if (!slider || !rail || !track) return;
    const speed = Math.max(50, Math.min(250, Number(slider.value) || 115));
    $("tickerSpeedValue").textContent = `${speed} пікс/с`;
    const update = () => {
      rail.style.setProperty("--ticker-start", `${rail.clientWidth}px`);
      rail.style.setProperty(
        "--ticker-seconds",
        `${((rail.clientWidth + track.scrollWidth) / speed).toFixed(2)}s`,
      );
    };
    window.requestAnimationFrame(update);
  }
  $("tickerSpeedInput").addEventListener("input", updateTickerPreview);
  window.addEventListener("resize", updateTickerPreview);
  function refreshAnnouncementPreview() {
    const form = $("announcementForm");
    const title = form.elements.title.value.trim(),
      message = form.elements.message.value.trim();
    $("announcementPreviewText").textContent =
      "ОГОЛОШЕННЯ  •  " +
      ([title, message].filter(Boolean).join(" • ") ||
        "Введіть текст оголошення");
    updateTickerPreview();
  }
  $("announcementForm").addEventListener("input", refreshAnnouncementPreview);
  refreshAnnouncementPreview();
  $("announcementReset").onclick = () => {
    $("announcementForm").reset();
    $("announcementForm").elements.id.value = "";
    $("announcementForm").elements.active.checked = true;
    $("announcementForm").elements.priority.value = 5;
  };
  $("eventReset").onclick = () => {
    $("eventForm").reset();
    $("eventForm").elements.id.value = "";
    $("eventForm").elements.active.checked = true;
    $("eventForm").elements.priority.value = 5;
    $("eventForm").elements.date.value = localDateISO();
  };

  $("subForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = e.currentTarget;
    const entries = [];
    for (let i = 1; i <= 2; i++) {
      const subject = f.elements[`subject${i}`].value.trim(),
        room = f.elements[`room${i}`].value.trim(),
        teacher = f.elements[`teacher${i}`].value.trim(),
        subgroup = f.elements[`subgroup${i}`].value;
      if (subject || room || teacher)
        entries.push({ subgroup, subject, room, teacher });
    }
    const item = {
      id: f.elements.id.value,
      active: f.elements.active.checked,
      date: f.elements.date.value,
      class: f.elements.class.value,
      lesson: Number(f.elements.lesson.value),
      scope: f.elements.scope.value,
      week: "ALL",
      day: "",
      note: f.elements.note.value,
      entries,
    };
    try {
      await api("/api/admin/item", {
        method: "POST",
        body: JSON.stringify({ kind: "substitution", op: "save", item }),
      });
      notify("Заміна збережена");
      resetSub();
      await refreshDashboard(true);
    } catch (err) {
      notify(err.message, "err");
    }
  });
  $("announcementForm").addEventListener("submit", (e) =>
    saveContentForm(e, "announcement"),
  );
  $("eventForm").addEventListener("submit", (e) => saveContentForm(e, "event"));
  async function saveContentForm(e, kind) {
    e.preventDefault();
    const f = e.currentTarget,
      item = collectForm(f);
    try {
      await api("/api/admin/item", {
        method: "POST",
        body: JSON.stringify({ kind, op: "save", item }),
      });
      notify("Збережено");
      f.reset();
      f.elements.id.value = "";
      if (f.elements.active) f.elements.active.checked = true;
      if (f.elements.priority) f.elements.priority.value = 5;
      await refreshDashboard(true);
    } catch (err) {
      notify(err.message, "err");
    }
  }

  $("dayOffForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = e.currentTarget;
    try {
      await api("/api/admin/calendar", {
        method: "POST",
        body: JSON.stringify({ kind: "daysOff", item: collectForm(f) }),
      });
      notify("День додано");
      f.reset();
      await refreshDashboard(true);
    } catch (err) {
      notify(err.message, "err");
    }
  });
  $("rangeForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = e.currentTarget;
    try {
      await api("/api/admin/calendar", {
        method: "POST",
        body: JSON.stringify({ kind: "ranges", item: collectForm(f) }),
      });
      notify("Період додано");
      f.reset();
      await refreshDashboard(true);
    } catch (err) {
      notify(err.message, "err");
    }
  });
  $("saveBells").onclick = async () => {
    const bells = [...document.querySelectorAll(".bell-row")].map((row) => ({
      lesson: Number(row.dataset.lesson),
      start: row.querySelector("[data-bell-start]").value,
      end: row.querySelector("[data-bell-end]").value,
    }));
    try {
      await api("/api/admin/bells", {
        method: "POST",
        body: JSON.stringify({ bells }),
      });
      notify("Дзвінки збережено");
      await refreshDashboard(true);
    } catch (err) {
      notify(err.message, "err");
    }
  };
  $("createBackup").onclick = async () => {
    try {
      const d = await api("/api/admin/action", {
        method: "POST",
        body: JSON.stringify({ action: "create_backup" }),
      });
      notify(d.message || "Backup створено");
      await refreshDashboard(true);
    } catch (err) {
      notify(err.message, "err");
    }
  };
  $("clearLogs").onclick = async () => {
    if (!confirm("Очистити журнал подій?")) return;
    try {
      await api("/api/admin/action", {
        method: "POST",
        body: JSON.stringify({ action: "clear_logs" }),
      });
      notify("Журнал очищено");
      await refreshDashboard(true);
    } catch (err) {
      notify(err.message, "err");
    }
  };
  $("otaCheck").onclick = async () => {
    try {
      const d = await api("/api/admin/action", {
        method: "POST",
        body: JSON.stringify({ action: "ota_check" }),
      });
      $("otaState").textContent = JSON.stringify(d, null, 2);
      notify(
        d.message || (d.available ? "Є нова версія" : "Оновлень немає"),
        d.ok === false ? "err" : "ok",
      );
    } catch (err) {
      $("otaState").textContent = err.message;
      notify(err.message, "err");
    }
  };
  $("otaApply").onclick = async () => {
    if (!confirm("Перед OTA автоматично буде створено backup. Продовжити?"))
      return;
    try {
      const d = await api("/api/admin/action", {
        method: "POST",
        body: JSON.stringify({ action: "ota_apply" }),
      });
      $("otaState").textContent = JSON.stringify(d, null, 2);
      notify(d.message || "OTA запущено");
      setTimeout(() => location.reload(), 4500);
    } catch (err) {
      $("otaState").textContent = err.message;
      notify(err.message, "err");
    }
  };

  $("screenForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const screen = collectForm(e.currentTarget);
    try {
      const d = await api("/api/admin/screen", {
        method: "POST",
        body: JSON.stringify({ op: "save", screen }),
      });
      notify(d.message || "Екран збережено");
      e.currentTarget.reset();
      e.currentTarget.elements.enabled.checked = true;
      await refreshDashboard(true);
    } catch (err) {
      notify(err.message, "err");
    }
  });

  $("copyMobile").onclick = async () => {
    try {
      await navigator.clipboard.writeText($("mobileUrl").value);
      notify("Mobile URL скопійовано");
    } catch (_) {
      $("mobileUrl").select();
      document.execCommand("copy");
      notify("Mobile URL скопійовано");
    }
  };
  $("mobileQrClass")?.addEventListener("change", renderMobileClassQr);
  $("copyMobileClass")?.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(mobileClassUrl());
      notify("URL класу скопійовано");
    } catch (_) {
      $("mobileClassUrl")?.select();
      document.execCommand("copy");
      notify("URL класу скопійовано");
    }
  });

  $("xlsxFile").addEventListener("change", () => {
    xlsxToken = "";
    xlsxPreviewData = null;
    $("xlsxApply").disabled = true;
    $("xlsxSummary").textContent =
      "Файл вибрано. Натисніть «ПЕРЕВІРИТИ / PREVIEW».";
    $("xlsxIssues").innerHTML = "";
    $("xlsxSamples").innerHTML = "";
  });
  $("xlsxPreview").onclick = async () => {
    const file = $("xlsxFile").files?.[0];
    if (!file) {
      notify("Оберіть .xlsx файл", "err");
      return;
    }
    $("xlsxPreview").disabled = true;
    $("xlsxApply").disabled = true;
    $("xlsxSummary").textContent = "Читання та перевірка XLSX…";
    try {
      const data_base64 = await fileAsBase64(file);
      const d = await api("/api/admin/xlsx/preview", {
        method: "POST",
        body: JSON.stringify({ file_name: file.name, data_base64 }),
      });
      xlsxToken = d.token || "";
      renderXlsxPreview(d);
      notify(
        d.ok === false ? "Preview містить помилки" : "XLSX перевірено",
        d.ok === false ? "err" : "ok",
      );
    } catch (err) {
      xlsxToken = "";
      $("xlsxSummary").textContent = err.message;
      notify(err.message, "err");
    } finally {
      $("xlsxPreview").disabled = false;
    }
  };
  $("xlsxApply").onclick = async () => {
    if (!xlsxToken) return;
    const target = $("xlsxTarget").value;
    if (
      !confirm(
        `Застосувати перевірений XLSX до «${$("xlsxTarget").selectedOptions[0].textContent}»? Перед цим буде створено backup.`,
      )
    )
      return;
    $("xlsxApply").disabled = true;
    try {
      const d = await api("/api/admin/xlsx/apply", {
        method: "POST",
        body: JSON.stringify({ token: xlsxToken, target }),
      });
      notify(
        `${d.message || "XLSX застосовано"} • ${d.entry_count || 0} записів`,
      );
      $("xlsxSummary").textContent +=
        `\n\nЗАСТОСОВАНО: ${d.file}\nBackup: ${d.backup?.name || "—"}\nSHA-256: ${d.sha256 || "—"}`;
      xlsxToken = "";
      await refreshDashboard(true);
    } catch (err) {
      notify(err.message, "err");
      $("xlsxApply").disabled = false;
    }
  };

  resetSub();
  setInterval(() => {
    if (!workspace.classList.contains("disabled"))
      refreshDashboard(false).catch(() => {});
  }, 10000);
  connect();
})();

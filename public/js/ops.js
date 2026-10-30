(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  let     dash = null,
    localPreviewTrackId = "";
  const today = () => {
    const d = new Date();
    d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
    return d.toISOString().slice(0, 10);
  };
  function toast(m, b = false) {
    const t = $("toast");
    t.textContent = m;
    t.className = "toast" + (b ? " bad" : "");
    clearTimeout(toast.t);
    toast.t = setTimeout(() => t.classList.add("hidden"), 2700);
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
  async function api(path, opt = {}) {
    const r = await fetch(path, {
        ...opt,
        headers: {
          "Content-Type": "application/json",
          ...(opt.headers || {}),
        },
        cache: "no-store",
      }),
      d = await r.json().catch(() => ({}));
    if (!r.ok) throw Error(d.error || `HTTP ${r.status}`);
    return d;
  }
  function formObj(form) {
    const o = {};
    for (const e of form.elements) {
      if (!e.name) continue;
      o[e.name] =
        e.type === "checkbox"
          ? e.checked
          : e.type === "number"
            ? Number(e.value)
            : e.value;
    }
    return o;
  }
  function activate(name) {
    document
      .querySelectorAll(".tabs button")
      .forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
    document
      .querySelectorAll(".tab")
      .forEach((x) => x.classList.toggle("active", x.id === `tab-${name}`));
  }
  document.querySelector(".tabs").onclick = (e) => {
    const b = e.target.closest("button[data-tab]");
    if (b) activate(b.dataset.tab);
  };
  async function connect() {
    const key = $("roleKey").value.trim();
    try {
      await window.LyceumAuth.login(key);
      $("roleKey").value = "";
      dash = await api("/api/ops/dashboard");
      $("signin").classList.add("hidden");
      $("app").classList.remove("hidden");
      setupSelectors();
      render();
    } catch (e) {
      toast(e.message, true);
    }
  }
  async function refresh() {
    try {
      dash = await api("/api/ops/dashboard");
      render();
    } catch (e) {
      toast(e.message, true);
    }
  }
  function setupSelectors() {
    const dir = dash.directory || {},
      classes = dir.classes || [],
      dutyClasses = [
        "10-А",
        "10-Б",
        "10-В",
        "10-Г",
        "11-А",
        "11-Б",
        "11-В",
        "11-Г",
      ];
    $("subForm").elements["class"].innerHTML = classes
      .map((x) => `<option>${esc(x)}</option>`)
      .join("");
    $("roomSelect").innerHTML = (dir.rooms || [])
      .map((x) => `<option>${esc(x)}</option>`)
      .join("");
    $("roomLesson").innerHTML = Array.from(
      { length: 12 },
      (_, i) => `<option value="${i + 1}">${i + 1} урок</option>`,
    ).join("");
    $("roomDate").value =
      $("roomScheduleDate").value =
      $("subForm").elements["date"].value =
        today();
    const df = $("dutySettingsForm");
    if (df) {
      df.elements["duty_rotation_start_class"].innerHTML = dutyClasses
        .map((x) => `<option>${esc(x)}</option>`)
        .join("");
      df.elements["duty_manual_class"].innerHTML =
        '<option value="">AUTO — за ротацією</option>' +
        dutyClasses.map((x) => `<option>${esc(x)}</option>`).join("");
    }
  }
  function render() {
    const s = dash.state || {},
      sys = dash.system || {},
      smart = dash.smart || {},
      stats = dash.stats || {},
      screens = dash.screens || [];
    $("updated").textContent =
      "Оновлено " + new Date().toLocaleTimeString("uk-UA");
    const mem = sys.memory || {},
      disk = sys.disk || {},
      memPct = mem.total ? Math.round((mem.used * 100) / mem.total) : 0,
      diskPct = disk.total ? Math.round((disk.used * 100) / disk.total) : 0;
    $("statusGrid").innerHTML = [
      ["Режим", s.mode || "—"],
      ["Час", s.clock || "—"],
      ["CPU", sys.cpu_temp_c == null ? "—" : sys.cpu_temp_c + "°C"],
      ["RAM", memPct + "%"],
      ["Диск", diskPct + "%"],
      ["Екрани", screens.filter((x) => x.online).length + "/" + screens.length],
    ]
      .map(
        (x) =>
          `<div class="tile"><span>${x[0]}</span><b>${esc(x[1])}</b></div>`,
      )
      .join("");
    const health = dash.health_alerts || [];
    $("healthList").innerHTML = health.length
      ? health
          .map(
            (x) =>
              `<div class="health ${esc(x.level)}">${esc(x.message)}</div>`,
          )
          .join("")
      : '<div class="health ok">Усі контрольовані параметри в нормі.</div>';
    const sch = s.schedule || {};
    $("phasePill").textContent = sch.phase || "—";
    $("nowGrid").innerHTML = [
      ["Урок", sch.lesson || "—"],
      [
        "До кінця",
        sch.seconds_to_lesson_end
          ? Math.ceil(sch.seconds_to_lesson_end / 60) + " хв"
          : "—",
      ],
      ["Погода", s.weather?.available ? `${s.weather.temperature}°` : "—"],
    ]
      .map(
        (x) =>
          `<div class="tile"><span>${x[0]}</span><b>${esc(x[1])}</b></div>`,
      )
      .join("");
    renderLogs();
    renderSmart(smart);
    renderMusic(smart);
    renderDuty();
    renderScreens();
    renderStats(stats);
    renderSubs();
  }
  function renderDuty() {
    const duty = dash.state?.duty || {},
      cfg = dash.config_public || {},
      f = $("dutySettingsForm");
    if (f) {
      f.elements["duty_class_enabled"].checked =
        cfg.duty_class_enabled !== false;
      f.elements["duty_skip_full_holiday_weeks"].checked =
        cfg.duty_skip_full_holiday_weeks !== false;
      f.elements["duty_class_label"].value =
        cfg.duty_class_label || "ЧЕРГОВИЙ КЛАС";
      f.elements["duty_rotation_start_date"].value =
        cfg.duty_rotation_start_date || "2026-09-01";
      f.elements["duty_rotation_start_class"].value =
        cfg.duty_rotation_start_class || "10-А";
      f.elements["duty_manual_class"].value = cfg.duty_manual_class || "";
      f.elements["duty_rotation_order_text"].value = (
        cfg.duty_rotation_order || [
          "10-А",
          "10-Б",
          "10-В",
          "10-Г",
          "11-А",
          "11-Б",
          "11-В",
          "11-Г",
        ]
      ).join(", ");
    }
    const current = duty.paused ? "КАНІКУЛИ" : duty.class || "—";
    const mode = duty.mode === "manual" ? "РУЧНИЙ" : "AUTO";
    const week = duty.academic_week_number
      ? `№ ${duty.academic_week_number}`
      : "—";
    const scheduleWeek = dash.state?.schedule?.week || {};
    const cycleLabel = scheduleWeek.paused
      ? `ПАУЗА → ${scheduleWeek.next_label || "—"}`
      : scheduleWeek.label || "—";
    $("dutyStatusGrid").innerHTML = [
      ["Чергує", current],
      ["Наступний", duty.next_class || "—"],
      ["Тип тижня", cycleLabel],
      ["Навчальний тиждень", week],
      ["Режим", mode],
      ["Початок тижня", duty.week_start || "—"],
      ["До", duty.week_end || "—"],
    ]
      .map(
        (x) =>
          `<div class="tile"><span>${x[0]}</span><b>${esc(x[1])}</b></div>`,
      )
      .join("");
    const notice = $("dutyNotice");
    if (duty.paused) {
      notice.innerHTML = `<b>Цикл на паузі: канікули.</b><span>Після канікул: ${esc(scheduleWeek.next_label || "наступний тип тижня")} • чергуватиме ${esc(duty.next_class || "—")}.</span>`;
    } else if (duty.class) {
      notice.innerHTML = `<b>★ Цього тижня чергує ${esc(duty.class)}</b><span>На TV цей клас виділяється і в звичайному режимі, і в укритті. Наступний: ${esc(duty.next_class || "—")}.</span>`;
    } else {
      notice.innerHTML = `<b>Чергування зараз неактивне.</b><span>${esc(duty.reason || "Перевірте налаштування ротації.")}</span>`;
    }
  }
  function renderLogs() {
    const logs = dash.logs || [];
    $("recentLogs").innerHTML =
      logs
        .slice(0, 12)
        .map(
          (x) =>
            `<div class="row-item"><b>${esc(x.message)}</b><span>${esc(x.kind)} • ${esc(x.actor)}</span><small>${esc(x.at)}</small></div>`,
        )
        .join("") || '<div class="row-item">Подій немає.</div>';
    $("auditList").innerHTML = logs
      .map(
        (x) =>
          `<div class="row-item"><b>${esc(x.message)}</b><span>${esc(x.kind)} • actor: ${esc(x.actor)}</span><small>${esc(x.at)}</small></div>`,
      )
      .join("");
  }
  function renderSmart(smart) {
    window.renderSlideshowSettings?.(dash.config_public || {});
    window.renderSlideshowPhotos?.(smart.media || []);
    const ns = smart.notifications || [];
    $("notificationList").innerHTML =
      ns
        .slice()
        .reverse()
        .map(
          (x) =>
            `<div class="row-item"><b>${esc(x.title)}</b><span>${esc(x.message)}</span><small>${esc(x.audience)} ${esc(x.target)} • ${esc(x.updated_at)}</small><div class="actions"><button class="danger" data-del="notification" data-id="${esc(x.id)}">ВИДАЛИТИ</button></div></div>`,
        )
        .join("") || '<div class="row-item">Сповіщень немає.</div>';
    const media = smart.media || [];
    $("mediaList").innerHTML =
      media
        .slice()
        .reverse()
        .map(
          (x) =>
            `<div class="row-item"><b>${esc(x.title || x.media_kind)}</b><span>${esc(x.url || x.message)}</span><small>${esc(x.media_kind)} • ${x.after_school_slideshow && x.media_kind === "video" ? "до кінця у слайд-шоу" : `${x.duration || 12} с`}</small><div class="actions"><button class="danger" data-del="media" data-id="${esc(x.id)}">ВИДАЛИТИ</button></div></div>`,
        )
        .join("") || '<div class="row-item">Media Library порожня.</div>';
    $("signageMedia").innerHTML =
      '<option value="">—</option>' +
      media
        .map(
          (x) =>
            `<option value="${esc(x.id)}">${esc(x.title || x.id)}</option>`,
        )
        .join("");
    $("signageList").innerHTML =
      (smart.signage_rules || [])
        .map(
          (x) =>
            `<div class="row-item"><b>${esc(x.name)}</b><span>${esc(x.mode)} • ${esc(x.start_time)}–${esc(x.end_time)} • ${esc(x.screen)}</span><div class="actions"><button class="danger" data-del="signage" data-id="${esc(x.id)}">ВИДАЛИТИ</button></div></div>`,
        )
        .join("") || '<div class="row-item">Правил немає.</div>';
    $("audioList").innerHTML =
      (smart.audio_events || [])
        .map(
          (x) =>
            `<div class="row-item"><b>${esc(x.name)}</b><span>${esc(x.time)} • ${esc(x.url)}</span><small>${esc((x.days || []).join(", "))}</small><div class="actions"><button class="danger" data-del="audio" data-id="${esc(x.id)}">ВИДАЛИТИ</button></div></div>`,
        )
        .join("") || '<div class="row-item">Аудіоподій немає.</div>';
    $("campusList").innerHTML = (smart.campuses || [])
      .map(
        (x) =>
          `<div class="row-item"><b>${esc(x.name)}</b><span>${esc(x.address)}</span><small>Поверхи: ${(x.floors || []).map(esc).join(", ")}</small><div class="actions"><button class="danger" data-del="campus" data-id="${esc(x.id)}">ВИДАЛИТИ</button></div></div>`,
      )
      .join("");
  }
  function renderMusic(smart) {
    const cfg = dash.config_public || {},
      tracks = smart.music_tracks || [],
      desired = dash.music || {};
    const f = $("musicSettingsForm");
    if (f) {
      for (const name of [
        "music_enabled",
        "music_breaks_enabled",
        "music_after_school_enabled",
        "music_shuffle",
      ]) {
        if (f.elements[name]) f.elements[name].checked = !!cfg[name];
      }
      for (const name of [
        "music_after_school_until",
        "music_volume_percent",
        "music_fade_seconds",
        "music_break_fade_before_end_seconds",
        "music_main_screen_id",
      ]) {
        if (f.elements[name]) f.elements[name].value = cfg[name] ?? "";
      }
    }
    $("musicTrackCount").textContent = `${tracks.length} треків`;
    $("musicTrackList").innerHTML =
      tracks
        .slice()
        .sort((a, b) => (a.order || 100) - (b.order || 100))
        .map(
          (x) =>
            `<div class="row-item"><b>${esc(x.title || "Музичний трек")}</b><span>${esc(x.artist || "")} ${x.artist ? "•" : ""} ${x.playlist === "break" ? "перерви" : x.playlist === "after_school" ? "після уроків" : "обидва плейлисти"}</span><small>${esc(x.url || "")} • order ${x.order ?? 100}</small><div class="actions"><button class="good" data-local-preview="${esc(x.id)}">💻 ЛОКАЛЬНО</button><button class="primary" data-test-track="${esc(x.id)}">📺 TV ТЕСТ 15 СЕК</button><button class="danger" data-del="music" data-id="${esc(x.id)}">ВИДАЛИТИ</button></div></div>`,
        )
        .join("") ||
      '<div class="row-item">Плейлист порожній. Завантажте перший аудіофайл.</div>';
    $("musicDesired").textContent = desired.allowed
      ? `${desired.playlist === "break" ? "ПЕРЕРВА" : "ПІСЛЯ УРОКІВ"} • PLAY`
      : `STOP • ${desired.reason || "—"}`;
    const screenId = cfg.music_main_screen_id || "main-hall",
      screen = (dash.screens || []).find((x) => x.id === screenId),
      ms = screen?.music_status || {};
    $("musicNow").innerHTML = ms.title
      ? `<b>${ms.state === "test-playing" ? "ТЕСТ" : "Зараз"}: ${esc(ms.title)}</b><span>${esc(ms.artist || "")} ${ms.playlist ? `• ${esc(ms.playlist)}` : ""}${ms.test_remaining ? ` • ще ${esc(ms.test_remaining)} с` : ""}</span><small>TV: ${esc(screenId)} • ${esc(ms.state || "—")} • volume ${esc(ms.volume || "0")}</small>`
      : `<b>Фонова музика: ${esc(ms.state || "не відтворюється")}</b><span>Бажаний режим: ${esc(desired.reason || "—")}</span><small>TV: ${esc(screenId)}</small>`;
  }
  function getMusicTracks() {
    return (dash?.smart?.music_tracks || []).filter(
      (x) => x && x.active !== false && x.url,
    );
  }
  function getLocalPreviewTrack(id = "") {
    const tracks = getMusicTracks()
      .slice()
      .sort(
        (a, b) =>
          (a.order || 100) - (b.order || 100) ||
          String(a.title || "").localeCompare(String(b.title || ""), "uk"),
      );
    return (
      (id ? tracks.find((x) => String(x.id) === String(id)) : tracks[0]) || null
    );
  }
  function localPreviewStatus(title, message, bad = false) {
    const box = $("localPreviewNow");
    if (!box) return;
    box.innerHTML = `<b>${esc(title)}</b><span>${esc(message || "")}</span>`;
    box.classList.toggle("bad", !!bad);
  }
  async function playLocalPreview(id = "") {
    const track = getLocalPreviewTrack(id);
    if (!track) return toast("У плейлисті немає активних треків", true);
    const audio = $("localMusicPreview");
    if (!audio) return toast("Локальний аудіоплеєр не знайдено", true);

    try {
      audio.pause();
      localPreviewTrackId = String(track.id || "");
      audio.src = String(track.url || "");
      const configured = Math.max(
        0,
        Math.min(100, Number(dash?.config_public?.music_volume_percent ?? 35)),
      );
      audio.volume = configured / 100;
      audio.currentTime = 0;
      await audio.play();
      localPreviewStatus(
        `💻 ЛОКАЛЬНО: ${track.title || "Музичний трек"}`,
        `${track.artist || "Без виконавця"} • ${configured}% • звук тільки в цьому браузері`,
      );
      toast("Локальне прослуховування запущено");
    } catch (err) {
      localPreviewTrackId = "";
      localPreviewStatus(
        "Локальне прослуховування не запустилося",
        err?.message || "Browser audio error",
        true,
      );
      toast("Браузер не зміг відтворити файл", true);
    }
  }
  function stopLocalPreview() {
    const audio = $("localMusicPreview");
    if (audio) {
      audio.pause();
      try {
        audio.currentTime = 0;
      } catch (_) {}
    }
    localPreviewTrackId = "";
    localPreviewStatus(
      "Локальне прослуховування: STOP",
      "Звук у цьому браузері зупинено.",
    );
  }
  function renderScreens() {
    $("screenList").innerHTML =
      (dash.screens || [])
        .map(
          (x) =>
            `<div class="row-item"><b>${esc(x.name || x.id)} ${x.online ? "🟢" : "🔴"}</b><span>${esc(x.building || "")} ${x.floor ? `• поверх ${esc(x.floor)}` : ""} ${x.zone ? `• ${esc(x.zone)}` : ""}</span><small>${esc(x.ip || "")} • ${esc(x.version || "")} • ${esc(x.profile || "")}${x.music_status?.title ? ` • ♫ ${esc(x.music_status.title)}` : ""}</small></div>`,
        )
        .join("") || '<div class="row-item">Екрани ще не зареєстровані.</div>';
  }
  function renderStats(s) {
    $("teacherStats").innerHTML = (s.top_teachers || [])
      .map((x) => `<tr><td>${esc(x[0])}</td><td><b>${x[1]}</b></td></tr>`)
      .join("");
    $("roomStats").innerHTML = (s.top_rooms || [])
      .map((x) => `<tr><td>${esc(x[0])}</td><td><b>${x[1]}</b></td></tr>`)
      .join("");
  }
  function renderSubs() {
    $("subList").innerHTML =
      (dash.content?.substitutions || [])
        .filter((x) => x.active !== false)
        .slice()
        .reverse()
        .map(
          (x) =>
            `<div class="row-item"><b>${esc(x.date)} • ${esc(x.class)} • ${esc(x.lesson)} урок</b><span>${(x.entries || []).map((e) => `${esc(e.subject)} ${e.room ? `(каб. ${esc(e.room)})` : ""}`).join("; ")}</span><small>${esc(x.note || "")}</small></div>`,
        )
        .join("") || '<div class="row-item">Активних замін немає.</div>';
  }
  async function saveItem(kind, item) {
    try {
      await api("/api/ops/item", {
        method: "POST",
        body: JSON.stringify({ kind, op: "save", item }),
      });
      toast("Збережено");
      await refresh();
    } catch (e) {
      toast(e.message, true);
    }
  }
  async function delItem(kind, id) {
    if (!confirm("Видалити запис?")) return;
    try {
      await api("/api/ops/item", {
        method: "POST",
        body: JSON.stringify({ kind, op: "delete", id }),
      });
      toast("Видалено");
      await refresh();
    } catch (e) {
      toast(e.message, true);
    }
  }
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-del]");
    if (b) delItem(b.dataset.del, b.dataset.id);
  });
  $("findFree").onclick = async () => {
    try {
      const d = await api(
        `/api/ops/free-rooms?date=${$("roomDate").value}&lesson=${$("roomLesson").value}`,
      );
      $("freeSummary").textContent =
        `Вільно ${d.free.length} із ${d.total} відомих кабінетів`;
      $("freeRooms").innerHTML =
        d.free
          .map((x) => `<span class="free-room">${esc(x)}</span>`)
          .join("") || '<span class="hint">Вільних не знайдено.</span>';
    } catch (e) {
      toast(e.message, true);
    }
  };
  $("findRoomSchedule").onclick = async () => {
    try {
      const d = await api(
        `/api/ops/room-schedule?room=${encodeURIComponent($("roomSelect").value)}&date=${$("roomScheduleDate").value}`,
      );
      $("roomSchedule").innerHTML =
        (d.lessons || [])
          .map(
            (x) =>
              `<article class="lesson"><div class="lesson-num">${x.lesson}</div><div class="lesson-body"><div class="time">${esc(x.start)} – ${esc(x.end)}</div><div class="entry"><div><b>${esc(x.subject)}</b><small>${esc(x.class)} • ${esc(x.teacher)}</small></div></div></div></article>`,
          )
          .join("") || '<div class="row-item">Кабінет вільний весь день.</div>';
    } catch (e) {
      toast(e.message, true);
    }
  };
  $("notificationForm").onsubmit = (e) => {
    e.preventDefault();
    saveItem("notification", formObj(e.target));
    e.target.reset();
  };
  $("mediaForm").onsubmit = (e) => {
    e.preventDefault();
    saveItem("media", formObj(e.target));
    e.target.reset();
  };
  $("signageForm").onsubmit = (e) => {
    e.preventDefault();
    saveItem("signage", formObj(e.target));
    e.target.reset();
  };
  $("audioForm").onsubmit = (e) => {
    e.preventDefault();
    const o = formObj(e.target);
    o.days = String(o.daysText || "")
      .split(",")
      .map((x) => x.trim())
      .filter(Boolean);
    delete o.daysText;
    saveItem("audio", o);
  };
  $("campusForm").onsubmit = (e) => {
    e.preventDefault();
    const o = formObj(e.target);
    o.floors = String(o.floorsText || "")
      .split(",")
      .map((x) => x.trim())
      .filter(Boolean);
    delete o.floorsText;
    saveItem("campus", o);
  };
  $("uploadMedia").onclick = async () => {
    const f = $("mediaFile").files?.[0];
    if (!f) return toast("Оберіть файл", true);
    if (f.size > 35 * 1024 * 1024) return toast("Файл більший за 35 MB", true);
    const b64 = await new Promise((res, rej) => {
      const r = new FileReader();
      r.onload = () => res(String(r.result));
      r.onerror = rej;
      r.readAsDataURL(f);
    });
    try {
      const d = await api("/api/ops/media/upload", {
        method: "POST",
        body: JSON.stringify({ file_name: f.name, data_base64: b64 }),
      });
      $("mediaForm").elements.url.value = d.url;
      $("mediaForm").elements.title.value = f.name;
      $("mediaForm").elements.media_kind.value = f.type.startsWith("video")
        ? "video"
        : "image";
      toast("Файл завантажено — додайте його до Media Library");
    } catch (e) {
      toast(e.message, true);
    }
  };
  $("dutySettingsForm").onsubmit = async (e) => {
    e.preventDefault();
    const o = formObj(e.target);
    const order = String(o.duty_rotation_order_text || "")
      .split(",")
      .map((x) => x.trim())
      .filter(Boolean);
    delete o.duty_rotation_order_text;
    o.duty_rotation_order = order;
    try {
      const d = await api("/api/ops/duty/settings", {
        method: "POST",
        body: JSON.stringify({ config: o }),
      });
      toast(d.message || "Чергування збережено");
      await refresh();
    } catch (err) {
      toast(err.message, true);
    }
  };
  $("dutyResetAuto").onclick = async () => {
    const f = $("dutySettingsForm");
    if (f) f.elements["duty_manual_class"].value = "";
    try {
      const d = await api("/api/ops/duty/settings", {
        method: "POST",
        body: JSON.stringify({ config: { duty_manual_class: "" } }),
      });
      toast(d.message || "AUTO-ротацію відновлено");
      await refresh();
    } catch (err) {
      toast(err.message, true);
    }
  };
  $("musicSettingsForm").onsubmit = async (e) => {
    e.preventDefault();
    const o = formObj(e.target);
    try {
      const d = await api("/api/ops/music/settings", {
        method: "POST",
        body: JSON.stringify({ config: o }),
      });
      toast(d.message || "Music Scheduler збережено");
      await refresh();
    } catch (err) {
      toast(err.message, true);
    }
  };
  $("musicTrackForm").onsubmit = (e) => {
    e.preventDefault();
    const o = formObj(e.target);
    saveItem("music", o);
    e.target.reset();
    e.target.elements.order.value = 100;
  };
  $("uploadMusic").onclick = async () => {
    const f = $("musicFile").files?.[0];
    if (!f) return toast("Оберіть аудіофайл", true);
    if (f.size > 35 * 1024 * 1024) return toast("Файл більший за 35 MB", true);
    const b64 = await new Promise((res, rej) => {
      const r = new FileReader();
      r.onload = () => res(String(r.result));
      r.onerror = rej;
      r.readAsDataURL(f);
    });
    try {
      const d = await api("/api/ops/media/upload", {
        method: "POST",
        body: JSON.stringify({ file_name: f.name, data_base64: b64 }),
      });
      const form = $("musicTrackForm");
      form.elements.url.value = d.url;
      form.elements.title.value = f.name.replace(/\.[^.]+$/, "");
      toast("Аудіофайл завантажено. Виберіть плейлист і додайте трек.");
    } catch (err) {
      toast(err.message, true);
    }
  };
  document.addEventListener("click", async (e) => {
    const local = e.target.closest("[data-local-preview]");
    if (local) {
      await playLocalPreview(local.dataset.localPreview || "");
      return;
    }

    const testTrack = e.target.closest("[data-test-track]");
    if (testTrack) {
      try {
        const d = await api("/api/ops/music/command", {
          method: "POST",
          body: JSON.stringify({
            command: "music-test",
            track_id: testTrack.dataset.testTrack,
          }),
        });
        toast(d.message || "TV тест 15 секунд надіслано");
        setTimeout(refresh, 700);
      } catch (err) {
        toast(`TV тест: ${err.message}`, true);
      }
      return;
    }

    const b = e.target.closest("[data-music-command]");
    if (!b) return;
    try {
      const d = await api("/api/ops/music/command", {
        method: "POST",
        body: JSON.stringify({ command: b.dataset.musicCommand }),
      });
      toast(d.message || "Команду надіслано на TV");
      setTimeout(refresh, 700);
    } catch (err) {
      toast(`TV: ${err.message}`, true);
    }
  });
  $("stopLocalPreview").onclick = stopLocalPreview;
  $("localMusicPreview").addEventListener("ended", () => {
    localPreviewTrackId = "";
    localPreviewStatus(
      "Локальне прослуховування: завершено",
      "Трек закінчився. TV не змінювався.",
    );
  });
  $("localMusicPreview").addEventListener("error", () => {
    const src = $("localMusicPreview").getAttribute("src") || "";
    localPreviewStatus(
      "Помилка локального аудіо",
      src ? `Не вдалося відкрити ${src}` : "Файл не вибрано",
      true,
    );
  });
  $("subForm").onsubmit = async (e) => {
    e.preventDefault();
    const o = formObj(e.target),
      item = {
        active: true,
        date: o.date,
        class: o.class,
        lesson: o.lesson,
        scope: o.scope,
        note: o.note,
        entries: [
          {
            subgroup: o.subgroup,
            subject: o.subject,
            room: o.room,
            teacher: o.teacher,
          },
        ],
      };
    try {
      await api("/api/ops/substitution", {
        method: "POST",
        body: JSON.stringify({ op: "save", item }),
      });
      toast("Заміна збережена та розіслана");
      e.target.reset();
      e.target.elements.date.value = today();
      await refresh();
    } catch (err) {
      toast(err.message, true);
    }
  };
  $("connect").onclick = connect;
  $("refresh").onclick = refresh;
  $("roleKey").value = "";
  connect();
  setInterval(() => {
    if (!$("app").classList.contains("hidden")) refresh();
  }, 60000);
})();

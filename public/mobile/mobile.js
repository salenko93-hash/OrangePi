(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const classes = [
    "10-А",
    "10-Б",
    "10-В",
    "10-Г",
    "11-А",
    "11-Б",
    "11-В",
    "11-Г",
  ];
  let offset = 0,
    deferredInstall = null,
    lastNotificationSeq = 0;
  const CLASS_STORAGE_KEY = "lyceumtv.mobile.class";
  const isStandalone = () =>
    window.matchMedia?.("(display-mode: standalone)")?.matches === true ||
    navigator.standalone === true;
  const isIOS = () => /iphone|ipad|ipod/i.test(navigator.userAgent || "");
  const isAndroid = () => /android/i.test(navigator.userAgent || "");

  function isoDate(add = 0) {
    const d = new Date();
    d.setDate(d.getDate() + add);
    const y = d.getFullYear(),
      m = String(d.getMonth() + 1).padStart(2, "0"),
      day = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${day}`;
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
  function fmtDate(s) {
    const [y, m, d] = String(s).split("-");
    return y ? `${d}.${m}.${y}` : s;
  }
  function timeToMinutes(value) {
    const m = /^(\d{1,2}):(\d{2})$/.exec(String(value || "").trim());
    if (!m) return null;
    const h = Number(m[1]),
      min = Number(m[2]);
    if (
      !Number.isInteger(h) ||
      !Number.isInteger(min) ||
      h < 0 ||
      h > 23 ||
      min < 0 ||
      min > 59
    )
      return null;
    return h * 60 + min;
  }
  function lessonTemporalState(lesson, dataDate) {
    if (String(dataDate || "") !== isoDate(0)) return "future";
    const start = timeToMinutes(lesson?.start),
      end = timeToMinutes(lesson?.end);
    if (start === null || end === null || end <= start) return "future";
    const now = new Date(),
      current = now.getHours() * 60 + now.getMinutes();
    if (current >= end) return "past";
    if (current >= start && current < end) return "current";
    return "future";
  }
  function entryHtml(e) {
    const group = e.subgroup
      ? `<span class="group">${esc(e.subgroup.replace(/\s+/g, ""))}</span>`
      : "";
    return `<div class="entry"><div><div class="subject">${group}${esc(e.subject || "—")}</div><div class="meta">${esc(e.teacher || "—")}</div></div><div class="room">${esc(e.room || "—")}</div></div>`;
  }
  function render(data) {
    $("pageTitle").textContent = data.title || "Розклад ліцею";
    $("dayLabel").textContent = data.day_label || "—";
    $("dateLabel").textContent = fmtDate(data.date || "");
    $("weekLabel").textContent = data.week?.label || "—";
    const holiday = $("holiday");
    if (data.holiday) {
      holiday.textContent = data.holiday;
      holiday.classList.remove("hidden");
    } else holiday.classList.add("hidden");

    const anns = $("announcementBox"),
      items = data.announcements || [];
    if (items.length) {
      anns.innerHTML = items
        .map(
          (x) =>
            `<div class="announcement"><strong>${esc(x.title || "ОГОЛОШЕННЯ")}</strong><div>${esc(x.message || "")}</div></div>`,
        )
        .join("");
      anns.classList.remove("hidden");
    } else anns.classList.add("hidden");

    const lessons = data.lessons || [];
    $("lessonList").innerHTML =
      lessons
        .map((x) => {
          const temporal = lessonTemporalState(x, data.date);
          const stateClass =
            temporal === "current"
              ? " current"
              : temporal === "past"
                ? " past"
                : "";
          const aria = temporal === "current" ? ' aria-current="true"' : "";
          return `<article class="lesson${x.substitution ? " sub" : ""}${stateClass}"${aria}>
    <div class="number"><b>${Number(x.lesson) || "—"}</b><span>УРОК</span></div>
    <div class="lesson-body"><div class="time">${esc(x.start || "—")} – ${esc(x.end || "—")}</div>
      ${(x.entries || []).length ? (x.entries || []).map(entryHtml).join("") : `<div class="empty">Немає заняття</div>`}
    </div></article>`;
        })
        .join("") ||
      (data.holiday
        ? ""
        : `<div class="holiday">На цей день уроків для класу немає.</div>`);
    $("updatedAt").textContent =
      `Оновлено ${new Date().toLocaleTimeString("uk-UA", { hour: "2-digit", minute: "2-digit" })}`;
  }
  function classDeepLink(cls = $("classSelect").value) {
    const u = new URL("/mobile/", location.origin);
    u.searchParams.set("class", cls);
    return u.toString();
  }
  function updateClassShare() {
    const cls = $("classSelect").value,
      url = classDeepLink(cls);
    $("shareClass").textContent = cls;
    $("classUrl").value = url;
    $("classQr").src = `/api/qr.svg?text=${encodeURIComponent(url)}`;
  }
  function syncClassToUrlAndStorage() {
    const cls = $("classSelect").value;
    localStorage.setItem(CLASS_STORAGE_KEY, cls);
    const u = new URL(location.href);
    u.searchParams.set("class", cls);
    history.replaceState(null, "", u);
    updateClassShare();
  }
  function installInstructionsHtml() {
    const secure = window.isSecureContext;
    if (isIOS())
      return `<p><b>iPhone / iPad (Safari)</b></p><ol><li>Відкрийте сторінку в Safari.</li><li>Натисніть <b>Поділитися</b>.</li><li>Оберіть <b>На початковий екран</b>.</li><li>Натисніть <b>Додати</b>.</li></ol><div class="install-help-note">Вибраний клас ${esc($("classSelect").value)} запам’ятається.</div>`;
    if (isAndroid())
      return `<p><b>Android / Chrome</b></p><ol><li>Натисніть меню <b>⋮</b>.</li><li>Оберіть <b>Додати на головний екран</b> або <b>Встановити додаток</b>.</li><li>Підтвердьте LyceumTV.</li></ol>${secure ? "" : `<div class="install-help-note">Це HTTP-адреса. Chrome може запропонувати лише «Додати на головний екран». Для повного PWA install зазвичай потрібен HTTPS.</div>`}`;
    return `<p><b>Додати LyceumTV</b></p><ol><li>Відкрийте меню браузера.</li><li>Оберіть <b>Встановити додаток</b> або <b>Додати на головний екран</b>.</li></ol>${secure ? "" : `<div class="install-help-note">Для повного PWA install браузер може вимагати HTTPS.</div>`}`;
  }
  function updateInstallUi() {
    const card = document.querySelector(".install-card"),
      btn = $("installBtn"),
      status = $("installStatus");
    if (isStandalone()) {
      card?.classList.add("installed");
      btn.textContent = "ВСТАНОВЛЕНО";
      btn.disabled = true;
      status.textContent = "LyceumTV уже запущено як встановлений застосунок.";
      return;
    }
    card?.classList.remove("installed");
    btn.disabled = false;
    if (deferredInstall) {
      btn.textContent = "ВСТАНОВИТИ LYCEUMTV";
      status.textContent = "Браузер готовий встановити LyceumTV як застосунок.";
    } else if (!window.isSecureContext) {
      btn.textContent = "ДОДАТИ НА ГОЛОВНИЙ ЕКРАН";
      status.textContent =
        "Локальна HTTP-адреса: покажу інструкцію для телефона.";
    } else {
      btn.textContent = "ВСТАНОВИТИ / ДОДАТИ";
      status.textContent =
        "Якщо native install недоступний, покажу інструкцію.";
    }
  }
  function showInstallHelp() {
    $("installHelpText").innerHTML = installInstructionsHtml();
    const dlg = $("installHelp");
    if (typeof dlg.showModal === "function") dlg.showModal();
    else alert(dlg.textContent);
  }
  async function copyText(value) {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(value);
      return true;
    }
    const el = document.createElement("textarea");
    el.value = value;
    el.style.position = "fixed";
    el.style.opacity = "0";
    document.body.appendChild(el);
    el.select();
    const ok = document.execCommand("copy");
    el.remove();
    return ok;
  }
  async function shareCurrentClass() {
    const cls = $("classSelect").value,
      url = classDeepLink(cls),
      data = {
        title: `LyceumTV • ${cls}`,
        text: `Актуальний розклад ${cls}`,
        url,
      };
    if (navigator.share) {
      try {
        await navigator.share(data);
        return;
      } catch (e) {
        if (e?.name === "AbortError") return;
      }
    }
    try {
      await copyText(url);
      $("statusLine").textContent = "Посилання на клас скопійовано";
      setTimeout(
        () =>
          ($("statusLine").textContent =
            "Актуальний розклад, заміни та дзвінки"),
        1800,
      );
    } catch (_) {}
  }
  function notificationKey(cls = $("classSelect").value) {
    return `lyceumtv.notifications.seq.${cls}`;
  }
  function renderNotificationInbox(items) {
    const box = $("notificationInbox");
    if (!box) return;
    box.innerHTML =
      (items || [])
        .slice()
        .reverse()
        .slice(0, 8)
        .map(
          (x) =>
            `<div class="notification-item ${esc(x.level || "info")}"><b>${esc(x.title || "LyceumTV")}</b><span>${esc(x.message || "")}</span><small>${esc(x.created_at || "")}</small></div>`,
        )
        .join("") || `<div class="empty">Нових повідомлень немає.</div>`;
  }
  async function showSystemNotification(item) {
    if (!item || Notification.permission !== "granted") return;
    try {
      const reg = await navigator.serviceWorker?.ready;
      if (reg) {
        await reg.showNotification(item.title || "LyceumTV", {
          body: item.message || "",
          icon: "/mobile/icons/icon-192.png",
          badge: "/mobile/icons/icon-192.png",
          tag: `lyceumtv-${item.id || item.seq}`,
          data: { url: classDeepLink() },
        });
        return;
      }
    } catch (_) {}
    try {
      new Notification(item.title || "LyceumTV", { body: item.message || "" });
    } catch (_) {}
  }
  async function loadNotifications(pushNew = false) {
    const cls = $("classSelect").value;
    try {
      const r = await fetch(
        `/api/notifications?class=${encodeURIComponent(cls)}&after=0`,
        { cache: "no-store" },
      );
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || `HTTP ${r.status}`);
      const items = d.items || [];
      const previous = Number(localStorage.getItem(notificationKey(cls)) || 0);
      const latest = items.length
        ? Math.max(...items.map((x) => Number(x.seq) || 0))
        : previous;
      if (pushNew && previous) {
        for (const item of items.filter((x) => (Number(x.seq) || 0) > previous))
          await showSystemNotification(item);
      }
      if (latest) {
        localStorage.setItem(notificationKey(cls), String(latest));
        lastNotificationSeq = latest;
      }
      renderNotificationInbox(items);
    } catch (_) {}
  }
  function offlineCacheKey(cls, date) {
    return `lyceumtv.mobile.cache.${cls}.${date}`;
  }

  async function load() {
    const cls = $("classSelect").value,
      date = isoDate(offset);
    syncClassToUrlAndStorage();
    $("statusLine").textContent = "Оновлення…";
    try {
      const r = await fetch(
        `/api/mobile/schedule?class=${encodeURIComponent(cls)}&date=${date}`,
        { cache: "no-store" },
      );
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || `HTTP ${r.status}`);
      render(d);
      localStorage.setItem(offlineCacheKey(cls, date), JSON.stringify(d));
      $("statusLine").textContent = navigator.onLine
        ? "Актуальний розклад, заміни та дзвінки"
        : "OFFLINE • показано останні збережені дані";
    } catch (e) {
      try {
        const cached = JSON.parse(
          localStorage.getItem(offlineCacheKey(cls, date)) || "null",
        );
        if (cached) {
          render(cached);
          $("statusLine").textContent =
            "OFFLINE • показано останні збережені дані";
        } else throw e;
      } catch (_) {
        $("lessonList").innerHTML =
          `<div class="holiday error">${esc(e.message)}</div>`;
        $("statusLine").textContent = "Не вдалося оновити дані";
      }
    }
    loadNotifications(false);
  }
  function setOffset(v) {
    offset = v;
    $("todayBtn").classList.toggle("active", v === 0);
    $("tomorrowBtn").classList.toggle("active", v === 1);
    load();
  }
  const qs = new URLSearchParams(location.search),
    requested = qs.get("class"),
    saved = localStorage.getItem(CLASS_STORAGE_KEY);
  $("classSelect").value = classes.includes(requested)
    ? requested
    : classes.includes(saved)
      ? saved
      : "10-А";
  syncClassToUrlAndStorage();
  $("classSelect").addEventListener("change", () => {
    syncClassToUrlAndStorage();
    lastNotificationSeq = Number(localStorage.getItem(notificationKey()) || 0);
    load();
  });
  $("todayBtn").onclick = () => setOffset(0);
  $("tomorrowBtn").onclick = () => setOffset(1);
  $("shareBtn").onclick = shareCurrentClass;
  $("copyClassUrlBtn").onclick = async () => {
    try {
      await copyText(classDeepLink());
      $("copyClassUrlBtn").textContent = "СКОПІЙОВАНО";
      setTimeout(() => ($("copyClassUrlBtn").textContent = "КОПІЮВАТИ"), 1500);
    } catch (_) {}
  };

  $("enableNotificationsBtn").onclick = async () => {
    if (!("Notification" in window))
      return ($("statusLine").textContent =
        "Цей браузер не підтримує системні сповіщення");
    const permission = await Notification.requestPermission();
    $("enableNotificationsBtn").textContent =
      permission === "granted" ? "УВІМКНЕНО" : "УВІМКНУТИ";
    if (permission === "granted") loadNotifications(false);
  };
  if ("Notification" in window && Notification.permission === "granted")
    $("enableNotificationsBtn").textContent = "УВІМКНЕНО";
  window.addEventListener("online", () => {
    $("statusLine").textContent = "Мережу відновлено";
    load();
  });
  window.addEventListener("offline", () => {
    $("statusLine").textContent = "OFFLINE • використовуються збережені дані";
  });

  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    deferredInstall = e;
    updateInstallUi();
  });
  window.addEventListener("appinstalled", () => {
    deferredInstall = null;
    updateInstallUi();
  });
  $("installBtn").onclick = async () => {
    if (isStandalone()) return;
    if (deferredInstall) {
      deferredInstall.prompt();
      try {
        await deferredInstall.userChoice;
      } catch (_) {}
      deferredInstall = null;
      updateInstallUi();
      return;
    }
    showInstallHelp();
  };

  if ("serviceWorker" in navigator)
    navigator.serviceWorker.register("/mobile/sw.js").catch(() => {});
  lastNotificationSeq = Number(localStorage.getItem(notificationKey()) || 0);
  updateClassShare();
  updateInstallUi();
  load();
  setInterval(load, 30000);
  setInterval(() => loadNotifications(true), 20000);
})();

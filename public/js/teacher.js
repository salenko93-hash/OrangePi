(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  let     directory = null,
    lastSeq = 0;
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
    toast.t = setTimeout(() => t.classList.add("hidden"), 2600);
  }
  async function api(path) {
    const r = await fetch(path, {
        cache: "no-store",
      }),
      d = await r.json().catch(() => ({}));
    if (!r.ok) throw Error(d.error || `HTTP ${r.status}`);
    return d;
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
  function nowMin() {
    const d = new Date();
    return d.getHours() * 60 + d.getMinutes();
  }
  function hm(v) {
    const m = /^(\d+):(\d\d)$/.exec(String(v || ""));
    return m ? +m[1] * 60 + +m[2] : -1;
  }
  function currentClass(x, date) {
    if (date !== today()) return "";
    const n = nowMin(),
      a = hm(x.start),
      b = hm(x.end);
    return a >= 0 && n >= a && n < b ? " current" : "";
  }
  async function connect() {
    const key = $("roleKey").value.trim();
    try {
      await window.LyceumAuth.login(key);
      $("roleKey").value = "";
      directory = await api("/api/teacher/directory");
      $("signin").classList.add("hidden");
      $("app").classList.remove("hidden");
      $("teacherSelect").innerHTML = (directory.teachers || [])
        .map((x) => `<option>${esc(x)}</option>`)
        .join("");
      $("dateInput").value = today();
      await load();
    } catch (e) {
      toast(e.message, true);
    }
  }
  async function load() {
    const teacher = $("teacherSelect").value,
      date = $("dateInput").value || today();
    if (!teacher) return;
    try {
      const d = await api(
        `/api/teacher/schedule?teacher=${encodeURIComponent(teacher)}&date=${encodeURIComponent(date)}`,
      );
      $("teacherTitle").textContent = teacher;
      $("dayInfo").textContent = `${d.day_label || ""} • ${d.date}`;
      $("lessonCount").textContent = `${d.lessons.length} уроків`;
      $("lessons").innerHTML =
        d.lessons
          .map(
            (x) =>
              `<article class="lesson${currentClass(x, date)}"><div class="lesson-num">${x.lesson}</div><div class="lesson-body"><div class="time">${esc(x.start)} – ${esc(x.end)}${x.substitution ? " • ЗАМІНА" : ""}</div><div class="entry"><div><b>${esc(x.subject)}</b><small>${esc(x.class)} ${esc(x.subgroup)}</small></div><span class="room-badge">${esc(x.room || "—")}</span></div></div></article>`,
          )
          .join("") || '<div class="row-item">Уроків немає.</div>';
      const current = d.lessons.find((x) => currentClass(x, date));
      $("teacherSummary").innerHTML = [
        ["Сьогодні", d.lessons.length],
        ["Зараз", current ? `${current.lesson} урок` : "—"],
        ["Кабінет", current?.room || "—"],
      ]
        .map(
          (x) =>
            `<div class="tile"><span>${x[0]}</span><b>${esc(x[1])}</b></div>`,
        )
        .join("");
      await loadNotifications(teacher);
    } catch (e) {
      toast(e.message, true);
    }
  }
  async function loadNotifications(teacher) {
    try {
      const d = await api(
        `/api/notifications?teacher=${encodeURIComponent(teacher)}&after=0`,
      );
      const items = d.items || [];
      if (items.length) lastSeq = Math.max(...items.map((x) => +x.seq || 0));
      $("notifications").innerHTML =
        items
          .slice()
          .reverse()
          .map(
            (x) =>
              `<div class="row-item"><b>${esc(x.title)}</b><span>${esc(x.message)}</span><small>${esc(x.created_at || "")}</small></div>`,
          )
          .join("") || '<div class="row-item">Нових сповіщень немає.</div>';
    } catch (_) {}
  }
  async function poll() {
    if (!$("app").classList.contains("hidden")) {
      const teacher = $("teacherSelect").value;
      try {
        const d = await api(
          `/api/notifications?teacher=${encodeURIComponent(teacher)}&after=${lastSeq}`,
        );
        for (const n of d.items || []) {
          lastSeq = Math.max(lastSeq, +n.seq || 0);
          if (Notification.permission === "granted")
            new Notification(n.title || "LyceumTV", { body: n.message || "" });
          toast(n.message || n.title);
        }
      } catch (_) {}
    }
    setTimeout(poll, 20000);
  }
  $("connect").onclick = connect;
  $("refresh").onclick = load;
  $("teacherSelect").onchange = load;
  $("dateInput").onchange = load;
  $("notifyBtn").onclick = async () => {
    if (!("Notification" in window))
      return toast("Браузер не підтримує сповіщення", true);
    const p = await Notification.requestPermission();
    toast(
      p === "granted" ? "Сповіщення увімкнено" : "Дозвіл не надано",
      p !== "granted",
    );
  };
  $("roleKey").value = "";
  connect();
  poll();
})();

(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const baseWidth = 1920,
    baseHeight = 1080;
  function fit() {
    const stage = $("stage");
    const w = innerWidth,
      h = innerHeight,
      s = Math.min(w / baseWidth, h / baseHeight);
    stage.style.transform = `translate3d(${(w - baseWidth * s) / 2}px,${(h - baseHeight * s) / 2}px,0) scale(${s})`;
  }
  addEventListener("resize", fit);
  fit();
  const labels = {
    MONDAY: "ПОНЕДІЛОК",
    TUESDAY: "ВІВТОРОК",
    WEDNESDAY: "СЕРЕДА",
    THURSDAY: "ЧЕТВЕР",
    FRIDAY: "П’ЯТНИЦЯ",
    SATURDAY: "СУБОТА",
  };
  const order = [
    "10-А",
    "10-Б",
    "10-В",
    "10-Г",
    "11-А",
    "11-Б",
    "11-В",
    "11-Г",
  ];
  const escape = (s) =>
    String(s ?? "").replace(
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
  const text = (s) =>
    String(s ?? "")
      .replace(/^(?:гр\.?|група|підгрупа)\s*\d+\s*[.:;\-]?\s*/i, "")
      .trim();
  function entry(e) {
    if (!e)
      return '<div class="entry-row empty-row"><div class="cell">—</div></div>';
    const subject = escape(e.subject || "—"),
      teacher = escape(text(e.teacher) || "—");
    return `<div class="entry-row"><div class="cell subject-cell"><span class="subject-text" data-subject="${subject}">${subject}</span></div><div class="cell room-cell">${escape(e.room || "—")}</div><div class="cell teacher-cell"><span class="teacher-text">${teacher}</span></div></div>`;
  }
  function card(name, entries, lesson) {
    return `<article class="class-card" data-class="${escape(name)}"><div class="class-side"><div class="class-name">${escape(name)}</div><div class="class-lesson">${lesson} УРОК</div></div><div class="card-table"><div class="table-head"><span>ПРЕДМЕТ</span><span>КАБ.</span><span>ВИКЛАДАЧ</span></div><div class="entry-list">${entries.length ? entries.slice(0, 2).map(entry).join("") : entry(null)}</div></div></article>`;
  }
  function adjustText() {
    document.querySelectorAll(".subject-text,.teacher-text").forEach((el) => {
      let max = el.classList.contains("subject-text") ? 28 : 18.5,
        min = el.classList.contains("subject-text") ? 19 : 13.5;
      el.style.fontSize = max + "px";
      while (max > min && el.scrollWidth > el.clientWidth + 2) {
        max -= 0.5;
        el.style.fontSize = max + "px";
      }
    });
  }
  function fillLessons() {
    const mode = $("demoMode").value === "shelter" ? "shelter" : "schedule",
      period = $("demoWeek").value;
    const bells =
      window.LYCEUM_DEMO_DATA[mode + "_" + period].bellSchedule || [];
    const el = $("demoLesson"),
      old = el.value || "3";
    el.innerHTML = bells
      .map(
        (x) =>
          `<option value="${Number(x.lesson)}">${Number(x.lesson)} (${escape(x.start)}–${escape(x.end)})</option>`,
      )
      .join("");
    el.value = old;
    if (!el.value) el.selectedIndex = 0;
  }
  function calendarStatus(value) {
    if (!value) return "";
    const calendar = window.LYCEUM_DEMO_CALENDAR || {};
    const range = (calendar.ranges || []).find(
      (r) => r.from <= value && value <= r.to,
    );
    if (range) return range.label || "Канікули";
    const open = (calendar.openEndedRanges || []).find(
      (r) => r.from <= value && (!r.to || value <= r.to),
    );
    if (open) return open.label || "Канікули";
    const off = (calendar.daysOff || []).find(
      (d) => (typeof d === "string" ? d : d.date) === value,
    );
    if (off)
      return typeof off === "string"
        ? "День без занять"
        : off.label || "День без занять";
    if (new Date(value + "T12:00:00").getDay() === 0) return "Вихідний день";
    return "";
  }
  function draw() {
    const mode = $("demoMode").value === "shelter" ? "shelter" : "schedule",
      period = $("demoWeek").value,
      day = $("demoDay").value,
      lesson = Number($("demoLesson").value) || 1;
    const data = window.LYCEUM_DEMO_DATA[mode + "_" + period];
    if (!data) return;
    const calendarLabel = calendarStatus($("demoDate").value);
    const paused = !!calendarLabel && !$("demoForceSchedule").checked;
    const daily = paused ? {} : data.days?.[day] || {};
    const entriesFor = (name) => daily[name]?.[String(lesson)] || [];
    $("leftCards").innerHTML = order
      .slice(0, 4)
      .map((name) => card(name, entriesFor(name), lesson))
      .join("");
    $("rightCards").innerHTML = order
      .slice(4)
      .map((name) => card(name, entriesFor(name), lesson))
      .join("");
    $("stage").className = mode === "shelter" ? "theme-alarm" : "theme-normal";
    $("headerTitle").textContent = paused
      ? "НАВЧАЛЬНИХ ЗАНЯТЬ НЕМАЄ"
      : mode === "shelter"
        ? "РОЗКЛАД В УКРИТТІ"
        : "РОЗКЛАД УРОКІВ";
    $("weekPill").textContent = paused
      ? "КАНІКУЛИ / ВИХІДНИЙ"
      : period === "numerator"
        ? "ЧИСЕЛЬНИК"
        : "ЗНАМЕННИК";
    $("dayLabel").textContent = labels[day] || day;
    const val = $("demoDate").value;
    $("dateLabel").textContent = val ? val.split("-").reverse().join(".") : "";
    const bell = (data.bellSchedule || []).find(
      (b) => Number(b.lesson) === lesson,
    );
    $("clock").textContent = bell?.start || "10:00";
    $("alarmMessage").classList.toggle("hidden", mode !== "shelter");
    $("alarmGuide").classList.toggle("hidden", mode !== "shelter");
    $("lessonBadge").textContent = paused ? "БЕЗ УРОКІВ" : lesson + " УРОК";
    $("timerLabel").textContent = paused
      ? calendarLabel.toUpperCase()
      : "ДЕМОНСТРАЦІЯ · УРОК";
    $("timerValue").textContent = paused ? "—" : bell?.end || "—";
    $("timerProgress").querySelector("span").style.width = "35%";
    $("weatherCity").textContent = "КРОПИВНИЦЬКИЙ";
    $("weatherCondition").textContent = "DEMO · БЕЗ ПРОГНОЗУ";
    $("weatherTemp").textContent = "—°";
    $("tvMobileQrCard").classList.add("hidden");
    $("messagePage").classList.toggle("hidden", !paused || mode === "shelter");
    if (paused) {
      $("messagePage").querySelector(".messageTitle").textContent =
        calendarLabel.toUpperCase();
      $("messagePage").querySelector(".messageSubtitle").textContent =
        "Занять за розкладом немає · " +
        $("demoDate").value.split("-").reverse().join(".");
    }
    $("silencePage").classList.add("hidden");
    $("announcement").classList.add("hidden");
    $("signageOverlay").classList.add("hidden");
    $("offlineBadge").classList.add("hidden");
    requestAnimationFrame(adjustText);
  }
  $("demoMode").addEventListener("change", () => {
    fillLessons();
    draw();
  });
  $("demoWeek").addEventListener("change", () => {
    fillLessons();
    draw();
  });
  $("demoForceSchedule").addEventListener("change", draw);
  $("demoDay").addEventListener("change", draw);
  $("demoLesson").addEventListener("change", draw);
  $("demoDate").addEventListener("change", () => {
    const s = $("demoDate").value;
    if (s) {
      const d = new Date(s + "T12:00:00"),
        day = d.getDay();
      if (day >= 1 && day <= 6)
        $("demoDay").value = [
          "",
          "MONDAY",
          "TUESDAY",
          "WEDNESDAY",
          "THURSDAY",
          "FRIDAY",
          "SATURDAY",
        ][day];
    }
    draw();
  });
  $("demoFullscreen").addEventListener("click", () => {
    if (!document.fullscreenElement)
      document.documentElement.requestFullscreen?.();
    else document.exitFullscreen?.();
  });
  $("demoHide").addEventListener("click", () =>
    document.body.classList.add("controls-hidden"),
  );
  $("demoOpen").addEventListener("click", () =>
    document.body.classList.remove("controls-hidden"),
  );
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") document.body.classList.remove("controls-hidden");
  });
  fillLessons();
  draw();
})();

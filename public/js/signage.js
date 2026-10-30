(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
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
  async function tick() {
    try {
      const q = new URLSearchParams(location.search),
        screen = q.get("screen") || "main-hall",
        r = await fetch(
          `/api/signage/current?screen=${encodeURIComponent(screen)}`,
          { cache: "no-store" },
        ),
        d = await r.json(),
        m = d.media || {},
        rule = d.rule || {};
      $("signageMedia").innerHTML = "";
      if (d.mode === "media" && m) {
        $("signageTitle").textContent = m.title || rule.name || "LyceumTV";
        $("signageMessage").textContent = m.message || "";
        if (m.url) {
          if (m.media_kind === "video")
            $("signageMedia").innerHTML =
              `<video src="${esc(m.url)}" autoplay muted loop playsinline></video>`;
          else $("signageMedia").innerHTML = `<img src="${esc(m.url)}" alt="">`;
        }
      } else if (d.mode === "welcome") {
        $("signageTitle").textContent = rule.name || "Ласкаво просимо";
        $("signageMessage").textContent = "Lyceum Smart Campus";
      } else if (d.mode === "events") {
        $("signageTitle").textContent = "Події ліцею";
        $("signageMessage").textContent =
          "Актуальні події дивіться на Smart Campus";
      } else {
        $("signageTitle").textContent = "РОЗКЛАД УРОКІВ";
        $("signageMessage").textContent =
          "Digital Signage зараз працює в режимі розкладу";
      }
    } catch (_) {
      $("signageMessage").textContent = "Немає зв’язку з LyceumTV";
    }
    setTimeout(tick, 10000);
  }
  tick();
})();

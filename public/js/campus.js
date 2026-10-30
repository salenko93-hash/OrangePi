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
  async function load() {
    try {
      const r = await fetch("/api/campus", { cache: "no-store" }),
        d = await r.json();
      if (!r.ok) throw Error(d.error || "HTTP " + r.status);
      $("campusName").textContent = d.name || "Lyceum Smart Campus";
      $("campusMeta").textContent = `${d.date || ""} • ${d.week?.label || ""}`;
      $("weekPill").textContent = d.week?.label || "—";
      const base = new URL(d.mobile_url || "/mobile/", location.origin);
      $("classGrid").innerHTML = (d.classes || [])
        .map((cls) => {
          const u = new URL(base);
          u.searchParams.set("class", cls);
          return `<a class="class-link" href="${esc(u.toString())}">${esc(cls)}</a>`;
        })
        .join("");
      $("announcements").innerHTML =
        (d.announcements || [])
          .map(
            (x) =>
              `<div class="row-item"><b>${esc(x.title || "Оголошення")}</b><span>${esc(x.message)}</span></div>`,
          )
          .join("") || '<div class="row-item">Оголошень немає.</div>';
      $("events").innerHTML =
        (d.events || [])
          .map(
            (x) =>
              `<div class="row-item"><b>${esc(x.title)}</b><span>${esc(x.message || "")}</span><small>${esc(x.start_time || "")} ${x.end_time ? `– ${esc(x.end_time)}` : ""}</small></div>`,
          )
          .join("") || '<div class="row-item">Подій немає.</div>';
      $("bells").innerHTML =
        (d.bells || [])
          .map(
            (x) =>
              `<span class="free-room">${x.lesson} • ${esc(x.start)}–${esc(x.end)}</span>`,
          )
          .join("") || '<span class="hint">Дзвінки недоступні.</span>';
      const campusUrl = location.origin + "/campus/";
      $("campusQr").src = `/api/qr.svg?text=${encodeURIComponent(campusUrl)}`;
    } catch (e) {
      $("campusMeta").textContent = "Не вдалося оновити Smart Campus";
    }
  }
  load();
  setInterval(load, 60000);
})();

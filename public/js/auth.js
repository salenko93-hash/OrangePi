(() => {
  "use strict";
  try {
    for (const name of ["adminKey", "opsKey", "teacherKey"])
      localStorage.removeItem(`lyceumtv.${name}`);
  } catch (_) {}
  let logout;
  window.LyceumAuth = {
    async login(key) {
      const response = await fetch(key ? "/api/auth/login" : "/api/auth/session", {
        method: key ? "POST" : "GET",
        headers: { "Content-Type": "application/json" },
        cache: "no-store",
        ...(key ? { body: JSON.stringify({ key }) } : {}),
      });
      const result = await response.json();
      if (!response.ok || !result.role) throw new Error(result.error || "Введіть ключ доступу");
      if (!logout) {
        logout = document.createElement("button");
        logout.textContent = "ВИЙТИ";
        logout.style.cssText = "position:fixed;right:12px;bottom:12px;z-index:9999";
        logout.addEventListener("click", async () => {
          const response = await fetch("/api/auth/logout", { method: "POST" });
          if (response.ok) location.reload();
        });
        document.body.append(logout);
      }
      return result;
    },
  };
})();

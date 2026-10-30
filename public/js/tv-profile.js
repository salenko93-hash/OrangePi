(() => {
  "use strict";
  if (new URLSearchParams(window.location.search).get("lite") === "1") {
    document.documentElement.classList.add("tv-lite");
  }
})();

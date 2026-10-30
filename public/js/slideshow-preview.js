(() => {
  "use strict";

  const slideshow = window.afterSchoolSlideshow;
  const files = document.getElementById("previewFiles");
  const library = document.getElementById("previewLibrary");
  const status = document.getElementById("previewStatus");
  const localOnly =
    location.protocol === "file:" ||
    new URLSearchParams(location.search).get("local") === "1";
  let objectUrls = [],
    musicUrl = "",
    soundEnabled = false;

  function fit() {
    const width = window.visualViewport?.width || innerWidth;
    const height = window.visualViewport?.height || innerHeight;
    const top =
      document.querySelector(".preview-toolbar").getBoundingClientRect()
        .bottom + 12;
    const availableHeight = Math.max(1, height - top);
    const scale = Math.min(width / 1920, availableHeight / 1080);
    document.getElementById("stage").style.transform =
      `translate3d(${(width - 1920 * scale) / 2}px,${top + (availableHeight - 1080 * scale) / 2}px,0) scale(${scale})`;
  }

  function releasePhotos() {
    for (const url of objectUrls) URL.revokeObjectURL(url);
    objectUrls = [];
  }

  files.addEventListener("change", () => {
    const selected = [...files.files];
    const accepted = selected.filter(
      (file) =>
        /\.(jpe?g|png|webp|mp4|webm)$/i.test(file.name) &&
        file.size > 0 &&
        file.size <=
          (/\.(mp4|webm)$/i.test(file.name) ? 200 : 15) * 1024 * 1024,
    );
    if (!accepted.length) {
      status.textContent =
        "Фото JPG/PNG/WEBP до 15 МБ або відео MP4/WEBM до 200 МБ.";
      return;
    }
    const urls = accepted.map((file) => URL.createObjectURL(file));
    slideshow.setPhotos(
      accepted.map((file, i) => ({
        id: String(i),
        url: urls[i],
        kind: /\.(mp4|webm)$/i.test(file.name) ? "video" : "image",
      })),
    );
    releasePhotos();
    objectUrls = urls;
    files.value = "";
    const count = accepted.filter(
      (file) => !/\.(mp4|webm)$/i.test(file.name),
    ).length;
    status.textContent =
      `Локальний перегляд: ${count} фото (${count * 3} с), ${accepted.length - count} відео до кінця. Файли не завантажуються на TV.` +
      (accepted.length < selected.length
        ? ` Пропущено файлів: ${selected.length - accepted.length}.`
        : "");
  });

  library.addEventListener("click", () => {
    slideshow.setSoundtrack(undefined);
    slideshow.setPhotos(null);
    if (musicUrl) {
      URL.revokeObjectURL(musicUrl);
      musicUrl = "";
    }
    releasePhotos();
    status.textContent =
      "Медіафайли з медіатеки. Для музики та звуку відео натисніть «УВІМКНУТИ ЗВУК». Перегляд працює в будь-який день і час.";
  });

  document.getElementById("previewSound").addEventListener("click", () => {
    soundEnabled = !soundEnabled;
    slideshow.setAudioAllowed(soundEnabled);
    document.getElementById("previewSound").textContent = soundEnabled
      ? "ВИМКНУТИ ЗВУК"
      : "УВІМКНУТИ ЗВУК";
  });
  document
    .getElementById("previewMusic")
    .addEventListener("change", (event) => {
      const file = event.target.files[0];
      if (!file) return;
      if (
        !/\.(mp3|wav|ogg|m4a)$/i.test(file.name) ||
        !file.size ||
        file.size > 35 * 1024 * 1024
      ) {
        status.textContent = "Оберіть MP3/WAV/OGG/M4A до 35 МБ.";
        return;
      }
      const previous = musicUrl;
      musicUrl = URL.createObjectURL(file);
      slideshow.setSoundtrack({ url: musicUrl, volume: 0.35 });
      if (previous) URL.revokeObjectURL(previous);
      event.target.value = "";
      status.textContent = `Музика: ${file.name}. Увімкніть звук кнопкою; трек повторюватиметься протягом показу фото.`;
    });

  document
    .getElementById("previewFullscreen")
    .addEventListener("click", async () => {
      try {
        if (document.fullscreenElement) await document.exitFullscreen();
        else await document.documentElement.requestFullscreen();
      } catch (_) {
        status.textContent =
          "Браузер не дозволив повноекранний режим. Можна продовжити у звичайному вікні.";
      }
    });
  document.addEventListener("fullscreenchange", () => {
    document.getElementById("previewFullscreen").textContent =
      document.fullscreenElement ? "ВИЙТИ З ПОВНОГО ЕКРАНА" : "НА ВЕСЬ ЕКРАН";
  });
  window.addEventListener("resize", fit);
  if ("ResizeObserver" in window)
    new ResizeObserver(fit).observe(document.querySelector(".preview-toolbar"));
  window.visualViewport?.addEventListener("resize", fit);
  window.addEventListener("pagehide", () => slideshow.setActive(false));
  window.addEventListener("pageshow", (event) => {
    if (event.persisted) slideshow.setActive(true);
  });
  if (localOnly) {
    slideshow.setPhotos([]);
    library.disabled = true;
    status.textContent =
      "Оберіть фото / відео й музику з комп’ютера. Цей перегляд працює без Orange Pi та без Інтернету.";
  }
  fit();
  slideshow.setActive(true);
})();

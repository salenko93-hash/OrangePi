(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const input = $("slideshowFiles"),
    upload = $("uploadSlideshow"),
    status = $("slideshowUploadStatus"),
    list = $("slideshowPhotoList");
  if (!input || !upload || !status || !list) return;
  const media = new Map();
  let settingsDirty = false;
  async function api(path, body, binary = false) {
    const response = await fetch(path, {
      method: "POST",
      cache: "no-store",
      headers: {
        "Content-Type": binary
          ? "application/octet-stream"
          : "application/json",
      },
      body: binary ? body : JSON.stringify(body),
    });
    const result = await response.json();
    if (!response.ok)
      throw new Error(result.error || `HTTP ${response.status}`);
    return result;
  }
  function kindOf(file) {
    if (/\.(jpe?g|png|webp)$/i.test(file.name)) return "image";
    if (/\.(mp4|webm)$/i.test(file.name)) return "video";
    if (/\.(mp3|wav|ogg|m4a)$/i.test(file.name)) return "audio";
    return "";
  }
  async function uploadFile(file, expected) {
    const kind = kindOf(file),
      limit = kind === "video" ? 200 : kind === "audio" ? 35 : 15;
    if (!kind || (expected && kind !== expected))
      throw new Error("Оберіть файл підтримуваного формату");
    if (!file.size || file.size > limit * 1024 * 1024)
      throw new Error(`Файл порожній або більший за ${limit} МБ`);
    return api(
      `/api/ops/media/upload-file?name=${encodeURIComponent(file.name)}`,
      file,
      true,
    );
  }
  window.renderSlideshowSettings = (cfg) => {
    if (!settingsDirty) {
      $("slideshowVolume").value = cfg.slideshow_volume_percent ?? 35;
      $("slideshowAudioScreen").value =
        cfg.slideshow_audio_screen_id || "main-hall";
    }
    $("slideshowMusicStatus").textContent = cfg.slideshow_music_url
      ? `Музика: ${cfg.slideshow_music_url}`
      : "Музику ще не додано.";
  };
  window.renderSlideshowPhotos = (records) => {
    media.clear();
    list.replaceChildren();
    const selected = records.filter(
      (item) =>
        item.after_school_slideshow &&
        ["image", "video"].includes(item.media_kind),
    );
    selected.sort(
      (a, b) =>
        Number(a.media_kind === "video") - Number(b.media_kind === "video"),
    );
    for (const item of selected) {
      media.set(item.id, item);
      const card = document.createElement("article");
      card.className = "slideshow-photo";
      const visual = document.createElement(
        item.media_kind === "video" ? "video" : "img",
      );
      visual.src = item.url;
      if (item.media_kind === "video") {
        visual.controls = true;
        visual.preload = "metadata";
        visual.muted = true;
      } else {
        visual.alt = item.title || "Фото слайд-шоу";
        visual.loading = "lazy";
      }
      const title = document.createElement("b");
      title.textContent = item.title || "Медіафайл";
      const kind = document.createElement("small");
      kind.textContent =
        item.media_kind === "video" ? "Відео · до кінця" : "Фото · 3 секунди";
      const button = document.createElement("button");
      button.type = "button";
      button.className = "ghost";
      button.textContent = "ПРИБРАТИ З ПОКАЗУ";
      button.dataset.slideshowRemove = item.id;
      card.append(visual, title, kind, button);
      list.append(card);
    }
    const count = selected.filter((item) => item.media_kind === "image").length;
    $("slideshowDuration").textContent =
      `${count} фото × 3 с = ${count * 3} с музичного супроводу; відео — після фото.`;
    if (!selected.length) {
      const empty = document.createElement("p");
      empty.className = "hint";
      empty.textContent = "Додайте фото або відео для післяурочного показу.";
      list.append(empty);
    }
  };
  upload.addEventListener("click", async () => {
    const files = [...input.files];
    if (!files.length) {
      status.textContent = "Спочатку оберіть фото або відео.";
      return;
    }
    upload.disabled = input.disabled = true;
    let saved = 0;
    const errors = [];
    try {
      for (const [index, file] of files.entries()) {
        status.textContent = `Завантаження ${index + 1} з ${files.length}: ${file.name}…`;
        try {
          const kind = kindOf(file);
          if (!["image", "video"].includes(kind))
            throw new Error("Потрібне фото JPG/PNG/WEBP або відео MP4/WEBM");
          const uploaded = await uploadFile(file, kind);
          await api("/api/ops/item", {
            kind: "media",
            item: {
              title: file.name.replace(/\.[^.]+$/, ""),
              url: uploaded.url,
              media_kind: kind,
              active: true,
              duration: 3,
              after_school_slideshow: true,
            },
          });
          saved++;
        } catch (error) {
          errors.push(`${file.name}: ${error.message}`);
        }
      }
      input.value = "";
      status.textContent =
        `Додано: ${saved} з ${files.length}. ` +
        (errors.length
          ? errors.join("; ")
          : "Фото — по 3 секунди, відео — до кінця.");
      $("refresh").click();
    } finally {
      upload.disabled = input.disabled = false;
    }
  });
  list.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-slideshow-remove]");
    const item = media.get(button?.dataset.slideshowRemove);
    if (!item) return;
    button.disabled = true;
    try {
      await api("/api/ops/item", {
        kind: "media",
        item: { ...item, after_school_slideshow: false },
      });
      status.textContent =
        "Файл прибрано з показу. Він залишається в медіатеці.";
      $("refresh").click();
    } catch (error) {
      status.textContent = error.message;
      button.disabled = false;
    }
  });
  $("uploadSlideshowMusic").addEventListener("click", async (event) => {
    const file = $("slideshowMusicFile").files[0];
    if (!file) {
      status.textContent = "Спочатку оберіть аудіофайл.";
      return;
    }
    event.target.disabled = true;
    try {
      status.textContent = "Завантаження музики…";
      const uploaded = await uploadFile(file, "audio");
      await api("/api/ops/slideshow/settings", {
        slideshow_music_url: uploaded.url,
      });
      $("slideshowMusicFile").value = "";
      status.textContent =
        "Музику додано. Трек повторюється протягом показу фото.";
      $("refresh").click();
    } catch (error) {
      status.textContent = error.message;
    } finally {
      event.target.disabled = false;
    }
  });
  $("removeSlideshowMusic").addEventListener("click", async (event) => {
    event.target.disabled = true;
    try {
      await api("/api/ops/slideshow/settings", { slideshow_music_url: "" });
      status.textContent = "Музичний супровід вимкнено.";
      $("refresh").click();
    } catch (error) {
      status.textContent = error.message;
    } finally {
      event.target.disabled = false;
    }
  });
  $("cleanupMedia").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      const preview = await api("/api/ops/media/cleanup", { dry_run: true });
      if (!preview.files) {
        status.textContent = "Невикористаних файлів старше години немає.";
        return;
      }
      const mb = (preview.bytes / 1024 / 1024).toFixed(1);
      if (
        !confirm(
          `Видалити ${preview.files} невикористаних файлів і звільнити ${mb} МБ? Файли, завантажені протягом останньої години, зберігаються.`,
        )
      )
        return;
      const result = await api("/api/ops/media/cleanup", { dry_run: false });
      status.textContent = `Видалено ${result.files} файлів; звільнено ${(result.bytes / 1024 / 1024).toFixed(1)} МБ.`;
    } catch (error) {
      status.textContent = error.message;
    } finally {
      button.disabled = false;
    }
  });

  $("slideshowSoundForm").addEventListener("input", () => {
    settingsDirty = true;
  });
  $("slideshowSoundForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await api("/api/ops/slideshow/settings", {
        slideshow_volume_percent: Number($("slideshowVolume").value),
        slideshow_audio_screen_id: $("slideshowAudioScreen").value.trim(),
      });
      settingsDirty = false;
      status.textContent = "Налаштування звуку збережено.";
      $("refresh").click();
    } catch (error) {
      status.textContent = error.message;
    }
  });
})();

(() => {
  "use strict";
  const root = document.getElementById("afterSchoolSlideshow");
  const panel = document.getElementById("afterSchoolInfo");
  if (!root || !panel) return;
  const layers = [...root.querySelectorAll(".after-school-slide")];
  const soundtrack = new Audio();
  soundtrack.loop = true;
  soundtrack.preload = "metadata";
  const INTERVAL_MS = 3000;
  let active = false,
    items = [],
    index = -1,
    layer = 0,
    pending = false;
  let generation = 0,
    requestId = 0,
    slideTimer = null,
    loadTimer = null,
    refreshTimer = null;
  let currentUrl = "",
    currentKind = "",
    localItems = null,
    localMusic;
  let music = { url: "", volume: 0.35, screen_id: "main-hall" };
  let audioAllowed = false,
    priorityPaused = false,
    audioPending = false,
    failedMusic = "";
  let musicRetryTimer = null,
    musicRetryCount = 0;
  const failed = new Set();
  const videos = layers.map((target) => target.querySelector("video"));

  function validUrl(url, local = false) {
    return (
      typeof url === "string" &&
      (url.startsWith("/media/") ||
        /^https:\/\//i.test(url) ||
        (local && url.startsWith("blob:")))
    );
  }
  function notifyChange() {
    window.dispatchEvent(new Event("lyceumtv:slideshow-change"));
  }
  function showGallery(visible) {
    root.classList.toggle("hidden", !visible);
    panel.classList.toggle("has-slideshow", visible);
  }
  function stopVideos() {
    for (const video of videos) {
      if (!video) continue;
      video.onloadeddata =
        video.onended =
        video.onerror =
        video.ontimeupdate =
          null;
      video.pause();
      video.removeAttribute("src");
      video.load();
    }
  }
  function cancelSlide() {
    requestId++;
    pending = false;
    clearTimeout(loadTimer);
    clearTimeout(slideTimer);
    for (const target of layers) {
      const img = target.querySelector("img");
      img.onload = img.onerror = null;
    }
    stopVideos();
  }
  function musicWanted() {
    return (
      active &&
      !priorityPaused &&
      audioAllowed &&
      currentKind === "image" &&
      !!music.url &&
      failedMusic !== music.url
    );
  }
  function syncAudio(restart = false) {
    const video = videos[layer];
    if (video) {
      video.muted =
        !audioAllowed || priorityPaused || video.dataset.autoplayMuted === "1";
      video.volume = music.volume;
    }
    if (!musicWanted()) {
      soundtrack.pause();
      return;
    }
    if (soundtrack.dataset.url !== music.url) {
      soundtrack.src = music.url;
      soundtrack.dataset.url = music.url;
      restart = true;
    }
    soundtrack.volume = music.volume;
    if (restart) {
      try {
        soundtrack.currentTime = 0;
      } catch (_) {}
    }
    if (!soundtrack.paused || audioPending) return;
    audioPending = true;
    soundtrack
      .play()
      .then(() => {
        if (!musicWanted()) soundtrack.pause();
      })
      .catch(() => {})
      .finally(() => {
        audioPending = false;
      });
  }
  soundtrack.onerror = () => {
    failedMusic = music.url;
    soundtrack.pause();
    clearTimeout(musicRetryTimer);
    if (!active || !music.url) return;
    const url = music.url;
    const wait = Math.min(30000, 1000 * 2 ** Math.min(musicRetryCount++, 5));
    musicRetryTimer = setTimeout(() => {
      if (!active || music.url !== url) return;
      failedMusic = "";
      soundtrack.load();
      syncAudio();
    }, wait);
  };
  function setMusic(value, local = false) {
    const url = validUrl(value?.url, local) ? value.url : "";
    const changed = music.url !== url;
    music = {
      url,
      volume: Math.max(0, Math.min(1, Number(value?.volume ?? 0.35) || 0)),
      screen_id: String(value?.screen_id || "main-hall"),
    };
    if (changed) {
      clearTimeout(musicRetryTimer);
      failedMusic = "";
      musicRetryCount = 0;
    }
    syncAudio(changed);
  }
  function scheduleNext() {
    clearTimeout(slideTimer);
    slideTimer = setTimeout(advance, INTERVAL_MS);
  }
  function armVideoTimeout(token, request, fail) {
    clearTimeout(loadTimer);
    loadTimer = setTimeout(() => {
      if (active && token === generation && request === requestId) fail();
    }, 10000);
  }
  function advance() {
    if (!active || pending || !items.length) return;
    let next = index;
    for (let n = 0; n < items.length; n++) {
      next = (next + 1) % items.length;
      if (!failed.has(items[next].url)) break;
    }
    const item = items[next];
    if (failed.has(item.url)) {
      cancelSlide();
      currentUrl = "";
      currentKind = "";
      syncAudio();
      showGallery(false);
      return;
    }
    // A single still photo remains visible; its three-second cycle restarts the track.
    if (
      item.url === currentUrl &&
      item.kind === "image" &&
      items.length === 1
    ) {
      syncAudio(true);
      scheduleNext();
      return;
    }
    pending = true;
    const token = generation,
      request = ++requestId;
    const target = layers[1 - layer],
      image = target.querySelector("img"),
      video = videos[1 - layer];
    let settled = false;
    const valid = () => active && token === generation && request === requestId;
    function fail() {
      if (!valid()) return;
      clearTimeout(loadTimer);
      pending = false;
      settled = true;
      if (video) video.pause();
      failed.add(item.url);
      advance();
    }
    function commit() {
      if (settled || !valid()) return;
      settled = true;
      pending = false;
      clearTimeout(loadTimer);
      const previous = videos[layer];
      if (previous) {
        previous.onended = previous.ontimeupdate = null;
        previous.pause();
      }
      index = next;
      currentUrl = item.url;
      currentKind = item.kind;
      target.classList.toggle("is-video", item.kind === "video");
      layers[layer].classList.remove("is-active");
      target.classList.add("is-active");
      layer = 1 - layer;
      showGallery(true);
      syncAudio(index === 0);
      if (item.kind === "video") {
        video.onended = () => {
          if (valid()) {
            clearTimeout(loadTimer);
            advance();
          }
        };
        video.ontimeupdate = () => {
          if (valid()) armVideoTimeout(token, request, fail);
        };
        armVideoTimeout(token, request, fail);
      } else {
        scheduleNext();
        const following = items[(index + 1) % items.length];
        if (following.kind === "image" && following.url !== currentUrl) {
          const preload = new Image();
          preload.src = following.url;
        }
      }
    }
    clearTimeout(slideTimer);
    clearTimeout(loadTimer);
    if (item.kind === "video") {
      currentKind = "video";
      syncAudio(); // Music ends with the photo block, before video buffering.
      if (!video) {
        fail();
        return;
      }
      video.onended = video.ontimeupdate = null;
      video.onerror = fail;
      video.dataset.autoplayMuted = "";
      video.muted = !audioAllowed || priorityPaused;
      video.volume = music.volume;
      let starting = false;
      video.onloadeddata = async () => {
        if (starting || !valid()) return;
        starting = true;
        try {
          await video.play();
        } catch (error) {
          if (!valid()) return;
          if (error.name !== "NotAllowedError") {
            fail();
            return;
          }
          video.dataset.autoplayMuted = "1";
          video.muted = true;
          try {
            await video.play();
          } catch (_) {
            fail();
            return;
          }
        }
        if (!valid()) return;
        commit();
      };
      video.src = item.url;
      video.load();
      armVideoTimeout(token, request, fail);
    } else {
      image.onload = () => {
        target.querySelector(".slide-backdrop").style.backgroundImage =
          `url(${JSON.stringify(item.url)})`;
        image.alt = "Фото слайд-шоу";
        commit();
      };
      image.onerror = fail;
      loadTimer = setTimeout(fail, 10000);
      image.src = item.url;
    }
  }
  async function refresh() {
    const token = generation;
    try {
      let next = localItems;
      if (next === null) {
        const response = await fetch("/api/slideshow", { cache: "no-store" });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = await response.json();
        if (!active || token !== generation) return;
        const title = document.getElementById("slideshowTitle");
        if (title)
          title.textContent =
            String(payload.title || "").trim() || "ЖИТТЯ ЛІЦЕЮ";
        setMusic(
          localMusic === undefined ? payload.music : localMusic,
          localMusic !== undefined,
        );
        next = payload.items;
      }
      if (!active || token !== generation) return;
      next = (Array.isArray(next) ? next : [])
        .filter((item) => item && validUrl(item.url, localItems !== null))
        .map((item) => ({
          id: item.id,
          url: item.url,
          kind: item.kind === "video" ? "video" : "image",
        }))
        .sort(
          (a, b) => Number(a.kind === "video") - Number(b.kind === "video"),
        );
      const changed = JSON.stringify(next) !== JSON.stringify(items);
      if (changed) {
        generation++;
        cancelSlide();
        items = next;
        index = -1;
        currentUrl = "";
        currentKind = "";
        soundtrack.pause();
        failed.clear();
        notifyChange();
      }
      if (!changed && failed.size) {
        const allFailed = failed.size === items.length;
        failed.clear();
        if (allFailed) {
          currentUrl = "";
          index = -1;
        }
      }
      if (!items.length) {
        showGallery(false);
        syncAudio();
      } else if (changed || !currentUrl) {
        advance();
      }
    } catch (_) {
      /* Keep the current playlist during a temporary network failure. */
    }
  }
  window.afterSchoolSlideshow = {
    setPhotos(value) {
      localItems = Array.isArray(value) ? value.slice() : null;
      generation++;
      cancelSlide();
      items = [];
      index = -1;
      currentUrl = "";
      currentKind = "";
      failed.clear();
      if (localMusic === undefined) setMusic(null);
      soundtrack.pause();
      showGallery(false);
      if (active) refresh();
    },
    setSoundtrack(value) {
      localMusic = value;
      setMusic(value, true);
      if (value === undefined && active) refresh();
    },
    setAudioAllowed(value) {
      const allowed = Boolean(value);
      if (allowed && !audioAllowed)
        for (const video of videos) if (video) video.dataset.autoplayMuted = "";
      audioAllowed = allowed;
      syncAudio();
    },
    setPriorityPaused(value) {
      priorityPaused = Boolean(value);
      syncAudio();
    },
    getStatus() {
      return {
        active,
        hasMedia: items.length > 0,
        kind: currentKind,
        musicUrl: music.url,
        audioScreenId: music.screen_id,
        photoCount: items.filter((item) => item.kind === "image").length,
      };
    },
    setActive(value) {
      value = Boolean(value);
      if (active === value) return;
      active = value;
      generation++;
      cancelSlide();
      clearInterval(refreshTimer);
      clearTimeout(musicRetryTimer);
      if (failedMusic) soundtrack.load();
      failedMusic = "";
      musicRetryCount = 0;
      currentUrl = "";
      currentKind = "";
      index = -1;
      failed.clear();
      notifyChange();
      syncAudio();
      if (!active) {
        showGallery(false);
        return;
      }
      if (items.length) advance();
      refresh();
      refreshTimer = setInterval(refresh, 30000);
    },
  };
})();

// Execute the actual module with controlled network/media timing.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const source = fs.readFileSync(
  path.join(__dirname, "../public/js/slideshow.js"),
  "utf8",
);
function fixture(fetch) {
  const audio = [];
  class Media {
    constructor() {
      this.dataset = {};
      this.paused = true;
      this.currentTime = 0;
      this.volume = 1;
      audio.push(this);
    }
    play() {
      this.paused = false;
      return Promise.resolve();
    }
    pause() {
      this.paused = true;
    }
    load() {}
    removeAttribute(name) {
      delete this[name];
    }
  }
  const classes = () => {
    const values = new Set();
    return {
      toggle: (k, on) => (on ? values.add(k) : values.delete(k)),
      add: (k) => values.add(k),
      remove: (k) => values.delete(k),
      has: (k) => values.has(k),
    };
  };
  const layers = Array.from({ length: 2 }, () => ({
    classList: classes(),
    img: {},
    video: new Media(),
    backdrop: { style: {} },
    querySelector(name) {
      return name === "img"
        ? this.img
        : name === "video"
          ? this.video
          : this.backdrop;
    },
  }));
  const root = { classList: classes(), querySelectorAll: () => layers },
    panel = { classList: classes() },
    title = { textContent: "Original" };
  const timers = new Map();
  let id = 0;
  const window = { dispatchEvent() {} };
  vm.runInNewContext(source, {
    window,
    document: {
      getElementById: (id) =>
        ({
          afterSchoolSlideshow: root,
          afterSchoolInfo: panel,
          slideshowTitle: title,
        })[id],
    },
    Audio: Media,
    Event: class {
      constructor(type) {
        this.type = type;
      }
    },
    Image: class {},
    fetch,
    setTimeout: (fn, ms) => {
      timers.set(++id, { fn, ms });
      return id;
    },
    clearTimeout: (id) => timers.delete(id),
    setInterval: () => 0,
    clearInterval: () => {},
  });
  const runTimer = (ms) => {
    const timer = [...timers].find(([, t]) => t.ms === ms);
    assert.ok(timer, `missing ${ms}ms timer`);
    timers.delete(timer[0]);
    timer[1].fn();
  };
  const loaded = (url) => {
    const target = layers.find((x) => x.img.src === url && x.img.onload);
    assert.ok(target, `missing image ${url}`);
    target.img.onload();
    return target;
  };
  return {
    api: window.afterSchoolSlideshow,
    layers,
    panel,
    title,
    timers,
    soundtrack: audio.at(-1),
    runTimer,
    loaded,
  };
}
const flush = () => new Promise((resolve) => setImmediate(resolve));
const response = (items) => async () => ({
  ok: true,
  json: async () => ({
    items,
    music: { url: "/media/song.mp3", volume: 0.35 },
  }),
});
(async () => {
  let resolve;
  const first = fixture(
    () =>
      new Promise((done) => {
        resolve = done;
      }),
  );
  first.api.setActive(true);
  first.api.setPhotos([{ id: "local", url: "blob:local" }]);
  resolve({ ok: true, json: async () => ({ title: "STALE", items: [] }) });
  await flush();
  assert.equal(first.title.textContent, "Original");
  assert.equal(first.layers[1].img.src, "blob:local");
  console.log("PASS: stale API response isolation");

  const second = fixture(
    response([{ url: "/media/hung.jpg" }, { url: "/media/good.jpg" }]),
  );
  second.api.setActive(true);
  await flush();
  second.runTimer(10000);
  second.loaded("/media/good.jpg");
  assert.ok(second.panel.classList.has("has-slideshow"));
  second.api.setActive(false);
  assert.equal(second.timers.size, 0);
  console.log("PASS: hung image recovery and timer cleanup");

  const mixed = fixture(
    response([
      { url: "/media/one.jpg" },
      { url: "/media/two.jpg" },
      { url: "/media/clip.mp4", kind: "video" },
    ]),
  );
  mixed.api.setAudioAllowed(true);
  mixed.api.setActive(true);
  await flush();
  mixed.loaded("/media/one.jpg");
  await flush();
  assert.equal(mixed.soundtrack.loop, true);
  assert.equal(mixed.soundtrack.paused, false);
  mixed.soundtrack.currentTime = 2;
  mixed.runTimer(3000);
  mixed.loaded("/media/two.jpg");
  assert.equal(
    mixed.soundtrack.currentTime,
    2,
    "track continues across photos",
  );
  mixed.runTimer(3000);
  assert.equal(
    mixed.soundtrack.paused,
    true,
    "music stops at photo duration, before video buffering",
  );
  const video = mixed.layers.find(
    (x) => x.video.src === "/media/clip.mp4",
  ).video;
  await video.onloadeddata();
  await flush();
  assert.equal(video.paused, false);
  assert.equal(video.muted, false);
  assert.ok(
    ![...mixed.timers.values()].some((t) => t.ms === 3000),
    "video never advances on the photo timer",
  );
  video.onended();
  mixed.loaded("/media/one.jpg");
  await flush();
  assert.equal(
    mixed.soundtrack.currentTime,
    0,
    "new photo cycle restarts soundtrack",
  );
  assert.equal(mixed.soundtrack.paused, false);
  assert.equal(video.paused, true);
  console.log(
    "PASS: photo duration, full video end, and soundtrack cycle/loop",
  );

  mixed.api.setPriorityPaused(true);
  assert.equal(mixed.soundtrack.paused, true);
  mixed.api.setPriorityPaused(false);
  await flush();
  assert.equal(mixed.soundtrack.paused, false);
  mixed.api.setActive(false);
  assert.equal(mixed.soundtrack.paused, true);
  assert.equal(mixed.timers.size, 0);
  assert.ok(mixed.layers.every((x) => x.video.paused));
  console.log(
    "PASS: priority audio and deactivation immediately silence playback",
  );

  const single = fixture(response([{ url: "/media/one.jpg" }]));
  single.api.setActive(true);
  await flush();
  single.loaded("/media/one.jpg");
  assert.equal(
    single.soundtrack.paused,
    true,
    "audio requires explicit permission",
  );
  single.api.setAudioAllowed(true);
  await flush();
  single.soundtrack.currentTime = 2;
  single.runTimer(3000);
  assert.equal(single.soundtrack.currentTime, 0);
  console.log("PASS: one-photo cycles and audio permission");

  const broken = fixture(
    response([
      { url: "/media/bad.mp4", kind: "video" },
      { url: "/media/good.mp4", kind: "video" },
    ]),
  );
  broken.api.setActive(true);
  await flush();
  broken.runTimer(10000);
  const good = broken.layers.find(
    (x) => x.video.src === "/media/good.mp4",
  ).video;
  await good.onloadeddata();
  await flush();
  assert.equal(good.paused, false);
  broken.api.setActive(false);
  assert.equal(good.paused, true);
  assert.equal(broken.timers.size, 0);
  console.log("PASS: hung video skip and video stop cleanup");

  const blocked = fixture(
    response([{ url: "/media/only.mp4", kind: "video" }]),
  );
  blocked.api.setAudioAllowed(true);
  blocked.api.setActive(true);
  await flush();
  const only = blocked.layers.find(
    (x) => x.video.src === "/media/only.mp4",
  ).video;
  let calls = 0;
  only.play = () => {
    if (!calls++) {
      const error = new Error("gesture required");
      error.name = "NotAllowedError";
      return Promise.reject(error);
    }
    only.paused = false;
    return Promise.resolve();
  };
  await only.onloadeddata();
  await flush();
  assert.equal(only.paused, false);
  assert.equal(only.muted, true, "muted fallback must stay muted after commit");
  assert.equal(
    blocked.soundtrack.paused,
    true,
    "video-only show never plays the photo soundtrack",
  );
  blocked.api.setAudioAllowed(false);
  blocked.api.setAudioAllowed(true);
  assert.equal(only.muted, false);
  blocked.api.setActive(false);
  console.log(
    "PASS: autoplay fallback stays muted until explicit audio permission",
  );
  const retry = fixture(response([{ url: "/media/retry.jpg" }]));
  retry.api.setAudioAllowed(true);
  retry.api.setActive(true);
  await flush();
  retry.loaded("/media/retry.jpg");
  await flush();
  retry.soundtrack.onerror();
  assert.equal(retry.soundtrack.paused, true);
  retry.runTimer(1000);
  await flush();
  assert.equal(
    retry.soundtrack.paused,
    false,
    "music recovers on the same URL",
  );
  retry.soundtrack.onerror();
  retry.api.setActive(false);
  assert.equal(retry.timers.size, 0);
  retry.api.setActive(true);
  await flush();
  retry.loaded("/media/retry.jpg");
  await flush();
  assert.equal(
    retry.soundtrack.paused,
    false,
    "stop/start clears previous music errors",
  );
  retry.api.setActive(false);
  console.log(
    "PASS: transient soundtrack errors retry and stop/start recovers the same track",
  );
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});

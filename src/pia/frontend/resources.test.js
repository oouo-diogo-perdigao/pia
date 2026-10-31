import test from "node:test";
import assert from "node:assert/strict";
import { fieldGroup } from "./settings-groups.js";

test("environment tabs preserve provider-specific classification", () => {
  assert.equal(fieldGroup({ name: "STT_GEMINI_API_KEY__SECRET" }), "STT");
  assert.equal(fieldGroup({ base: "TTS_DEVICE" }), "TTS");
  assert.equal(fieldGroup({ base: "ICE_COMFYUI_URL" }), "Imagens · ICE");
  assert.equal(fieldGroup({ base: "GROQ_API_KEY" }), "LLMs");
  assert.equal(fieldGroup({ base: "OVE_THRESHOLD" }), "Voz e áudio");
  assert.equal(fieldGroup({ base: "PORT" }), "Geral");
});

test("shared player validates URLs and publishes play/pause state", async () => {
  const events = [];
  globalThis.location = { origin: "http://localhost:8762" };
  globalThis.window = { addEventListener() {} };
  globalThis.fetch = async (url, options) => {
    events.push(JSON.parse(options.body));
    return { ok: true, json: async () => ({ ok: true }) };
  };
  globalThis.Audio = class {
    constructor() {
      this.paused = true;
      this.ended = false;
      this.duration = 120;
      this.currentTime = 0;
      this.handlers = {};
      this.src = "";
    }
    addEventListener(name, fn) {
      this.handlers[name] = fn;
    }
    getAttribute() {
      return this.src;
    }
    removeAttribute() {
      this.src = "";
    }
    load() {}
    async play() {
      this.paused = false;
      this.handlers.play();
    }
    pause() {
      this.paused = true;
      this.handlers.pause();
    }
  };
  const media = await import("../media.js");
  let state;
  const unsubscribe = media.subscribeMedia((value) => {
    state = value;
  });
  try {
    await assert.rejects(media.playMedia("https://example.com/private.mp3"));
    await media.playMedia("/api/pia/music/files/track.mp3", "Track");
    assert.equal(state.title, "Track");
    assert.equal(state.playing, true);
    assert.equal(events.at(-1).playing, true);
    media.seekMedia(42);
    assert.equal(media.mediaSnapshot().current, 42);
    media.pauseMedia();
    assert.equal(events.at(-1).playing, false);
  } finally {
    media.stopMedia();
    unsubscribe();
  }
});

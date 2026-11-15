import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const {
  sanitizeSvgMarkup,
  resolveAvatarUrl,
  createMiniController,
} = require("../../piamini/mini.js");

function makeFakeStage(initialSvg = '<svg class="pia"></svg>') {
  const props = {};
  const classes = new Set();
  const fakeMouth = { style: { opacity: "0" } };
  const fakeTalking = { style: { animationPlayState: "paused" } };
  let html = initialSvg;
  return {
    get innerHTML() {
      return html;
    },
    set innerHTML(val) {
      html = val;
    },
    style: {
      setProperty(k, v) {
        props[k] = v;
      },
      removeProperty(k) {
        delete props[k];
      },
      _props: props,
    },
    classList: {
      toggle(name, force) {
        if (force) classes.add(name);
        else classes.delete(name);
      },
      has(name) {
        return classes.has(name);
      },
    },
    querySelectorAll(sel) {
      if (html.indexOf("no-anim") >= 0) return [];
      if (sel === ".enable-mouth") return [fakeMouth];
      if (sel === ".animation-talking") return [fakeTalking];
      return [];
    },
    _fakeMouth: fakeMouth,
    _fakeTalking: fakeTalking,
  };
}

describe("piamini controller", () => {
  it("resolves avatar URLs relative to base and skips /pia.svg", () => {
    assert.equal(resolveAvatarUrl("http://127.0.0.1:8080", "/pia.svg"), "");
    assert.equal(
      resolveAvatarUrl("http://127.0.0.1:8080/", "/bots/secretaria/avatar.svg"),
      "http://127.0.0.1:8080/bots/secretaria/avatar.svg",
    );
    assert.equal(
      resolveAvatarUrl("http://127.0.0.1:8080", "https://example.com/a.svg"),
      "https://example.com/a.svg",
    );
  });

  it("rejects dangerous SVG payloads in fallback sanitizer", () => {
    assert.equal(sanitizeSvgMarkup("<svg><script>alert(1)</script></svg>"), "");
    assert.equal(sanitizeSvgMarkup('<svg onload="x()"></svg>'), "");
    assert.match(
      sanitizeSvgMarkup('<svg viewBox="0 0 10 10"><circle r="4"/></svg>'),
      /^<svg /,
    );
  });

  it("switches to bot SVG with colors while playing and restores PIA SVG when idle", async () => {
    const stage = makeFakeStage(
      '<svg class="pia"><g class="enable-mouth"/><g class="animation-talking"/></svg>',
    );
    let fetchCalls = 0;
    const ctrl = createMiniController({
      stage,
      base: "http://127.0.0.1:8080",
      fetchFn: async (url) => {
        fetchCalls += 1;
        assert.equal(url, "http://127.0.0.1:8080/bots/secretaria/avatar.svg");
        return {
          ok: true,
          text: async () =>
            '<svg class="secretaria"><g class="enable-mouth"/><g class="animation-talking"/></svg>',
        };
      },
    });

    ctrl.handleStatus({
      status: "playing",
      phase: "playing",
      epoch: 1,
      seq: 1,
      speaker_id: "secretaria",
      avatar_url: "/bots/secretaria/avatar.svg",
      avatar_colors: { primary: "#111", accent: "#222", eyes: "#fff" },
    });

    await new Promise((r) => setTimeout(r, 10));
    assert.equal(fetchCalls, 1);
    assert.match(stage.innerHTML, /class="secretaria"/);
    assert.equal(stage.style._props["--bot-primary"], "#111");
    assert.equal(stage._fakeMouth.style.opacity, "1");
    assert.equal(stage._fakeTalking.style.animationPlayState, "running");

    // Idle restores default PIA SVG and clears CSS color variables
    ctrl.handleStatus({
      status: "idle",
      phase: "completed",
      epoch: 1,
      seq: 2,
      speaker_id: "secretaria",
      avatar_url: "/bots/secretaria/avatar.svg",
    });
    assert.match(stage.innerHTML, /class="pia"/);
    assert.equal(stage.style._props["--bot-primary"], undefined);
    assert.equal(stage._fakeMouth.style.opacity, "0");
    assert.equal(stage._fakeTalking.style.animationPlayState, "paused");

    // Playing again hits cache without refetching
    ctrl.handleStatus({
      status: "playing",
      phase: "playing",
      epoch: 1,
      seq: 3,
      speaker_id: "secretaria",
      avatar_url: "/bots/secretaria/avatar.svg",
    });
    assert.equal(fetchCalls, 1);
    assert.match(stage.innerHTML, /class="secretaria"/);
  });

  it("uses fallback animation class when custom SVG lacks .enable-mouth and ignores out-of-order seq", async () => {
    const stage = makeFakeStage();
    const ctrl = createMiniController({
      stage,
      base: "http://127.0.0.1:8080",
      fetchFn: async () => ({
        ok: true,
        text: async () => '<svg class="no-anim"><circle r="10"/></svg>',
      }),
    });

    ctrl.handleStatus({
      status: "playing",
      phase: "playing",
      epoch: 2,
      seq: 5,
      speaker_id: "bot-1",
      avatar_url: "/api/pia/openbot/avatars/a1",
    });
    await new Promise((r) => setTimeout(r, 10));
    assert.equal(stage.classList.has("bot-speaking-fallback"), true);

    // Out-of-order older seq=4 in same epoch is ignored
    ctrl.handleStatus({
      status: "idle",
      phase: "idle",
      epoch: 2,
      seq: 4,
      speaker_id: "pia",
    });
    assert.equal(stage.classList.has("bot-speaking-fallback"), true);

    // Newer seq=6 stops fallback animation
    ctrl.handleStatus({
      status: "idle",
      phase: "idle",
      epoch: 2,
      seq: 6,
      speaker_id: "pia",
    });
    assert.equal(stage.classList.has("bot-speaking-fallback"), false);
  });
});

(function () {
  var FORBIDDEN_TAGS = {
    script: true,
    foreignobject: true,
    iframe: true,
    object: true,
    embed: true,
    link: true,
    meta: true,
  };

  function sanitizeSvgMarkup(raw) {
    if (typeof raw !== "string") return "";
    var trimmed = raw.trim();
    if (!trimmed) return "";
    if (typeof DOMParser === "undefined") {
      if (/<script|<foreignObject|\son[a-z]+\s*=/i.test(trimmed)) return "";
      var idx = trimmed.search(/<svg[\s>]/i);
      return idx >= 0 ? trimmed.slice(idx) : "";
    }
    var parser = new DOMParser();
    var doc = parser.parseFromString(trimmed, "image/svg+xml");
    if (!doc || doc.querySelector("parsererror")) return "";
    var root = doc.documentElement;
    if (!root || root.nodeName.toLowerCase() !== "svg") return "";

    var walk = function (node) {
      var children = Array.prototype.slice.call(node.children || []);
      for (var i = 0; i < children.length; i++) {
        var child = children[i];
        var tag = child.nodeName.toLowerCase();
        if (FORBIDDEN_TAGS[tag]) {
          child.parentNode.removeChild(child);
          continue;
        }
        var attrs = Array.prototype.slice.call(child.attributes || []);
        for (var j = 0; j < attrs.length; j++) {
          var attrName = attrs[j].name.toLowerCase();
          var attrVal = String(attrs[j].value || "");
          if (
            attrName.indexOf("on") === 0 ||
            /^\s*javascript:/i.test(attrVal) ||
            (attrName === "style" && /url\s*\(/i.test(attrVal))
          ) {
            child.removeAttribute(attrs[j].name);
          }
        }
        if (
          tag === "style" &&
          /url\s*\(|@import/i.test(child.textContent || "")
        ) {
          child.textContent = "";
        }
        walk(child);
      }
    };

    var rootAttrs = Array.prototype.slice.call(root.attributes || []);
    for (var k = 0; k < rootAttrs.length; k++) {
      if (rootAttrs[k].name.toLowerCase().indexOf("on") === 0) {
        root.removeAttribute(rootAttrs[k].name);
      }
    }
    walk(root);
    return new XMLSerializer().serializeToString(root);
  }

  function resolveAvatarUrl(base, avatarUrl) {
    if (!avatarUrl || avatarUrl === "/pia.svg") return "";
    if (/^https?:\/\//i.test(avatarUrl)) return avatarUrl;
    if (avatarUrl.charAt(0) === "/") {
      return String(base || "").replace(/\/+$/, "") + avatarUrl;
    }
    return "";
  }

  function createMiniController(options) {
    var stage = options.stage;
    var base = String(options.base || "").replace(/\/+$/, "");
    var fetchFn =
      options.fetchFn ||
      (typeof fetch !== "undefined" ? fetch.bind(window) : null);
    var defaultSvg =
      options.defaultSvg !== undefined ? options.defaultSvg : stage.innerHTML;
    var svgCache = new Map();
    var currentAvatarKey = "pia";
    var currentEpoch = null;
    var currentSeq = -1;
    var renderToken = 0;
    var activeController = null;
    var lastStatus = null;

    function applyColors(colors) {
      if (!stage || !stage.style) return;
      var c = colors && typeof colors === "object" ? colors : null;
      if (c && c.primary)
        stage.style.setProperty("--bot-primary", String(c.primary));
      else stage.style.removeProperty("--bot-primary");
      if (c && c.accent)
        stage.style.setProperty("--bot-accent", String(c.accent));
      else stage.style.removeProperty("--bot-accent");
      if (c && c.eyes) stage.style.setProperty("--bot-eyes", String(c.eyes));
      else stage.style.removeProperty("--bot-eyes");
    }

    function applySpeakingState(talkingNow) {
      if (!stage) return;
      var mouths = stage.querySelectorAll
        ? stage.querySelectorAll(".enable-mouth")
        : [];
      var talkings = stage.querySelectorAll
        ? stage.querySelectorAll(".animation-talking")
        : [];
      var hasAnimTargets = mouths.length > 0 || talkings.length > 0;
      for (var i = 0; i < mouths.length; i++) {
        mouths[i].style.opacity = talkingNow ? "1" : "0";
      }
      for (var j = 0; j < talkings.length; j++) {
        talkings[j].style.animationPlayState = talkingNow
          ? "running"
          : "paused";
      }
      if (stage.classList) {
        stage.classList.toggle(
          "bot-speaking-fallback",
          Boolean(talkingNow && !hasAnimTargets),
        );
      }
    }

    function restoreDefaultAvatar() {
      applyColors(null);
      if (currentAvatarKey !== "pia") {
        stage.innerHTML = defaultSvg;
        currentAvatarKey = "pia";
      }
    }

    function handleStatus(value) {
      if (!value || typeof value !== "object") return;
      var epoch = typeof value.epoch === "number" ? value.epoch : null;
      var seq = typeof value.seq === "number" ? value.seq : null;
      if (
        epoch !== null &&
        currentEpoch !== null &&
        epoch === currentEpoch &&
        seq !== null &&
        seq < currentSeq
      ) {
        return;
      }
      if (epoch !== null) currentEpoch = epoch;
      if (seq !== null) currentSeq = seq;
      lastStatus = value;

      var phase = String(value.phase || value.status || "idle").toLowerCase();
      var isPlaying = value.status === "playing" || phase === "playing";
      var isPaused = phase === "paused";
      var isActive = isPlaying || isPaused;
      var resolvedUrl =
        isActive && value.speaker_id && value.speaker_id !== "pia"
          ? resolveAvatarUrl(base, value.avatar_url)
          : "";

      if (!isActive || !resolvedUrl) {
        renderToken += 1;
        if (activeController) {
          activeController.abort();
          activeController = null;
        }
        restoreDefaultAvatar();
        applySpeakingState(isPlaying);
        return;
      }

      applyColors(value.avatar_colors);

      if (resolvedUrl === currentAvatarKey) {
        applySpeakingState(isPlaying);
        return;
      }

      if (svgCache.has(resolvedUrl)) {
        renderToken += 1;
        if (activeController) {
          activeController.abort();
          activeController = null;
        }
        stage.innerHTML = svgCache.get(resolvedUrl);
        currentAvatarKey = resolvedUrl;
        applySpeakingState(isPlaying);
        return;
      }

      if (!fetchFn) {
        restoreDefaultAvatar();
        applySpeakingState(isPlaying);
        return;
      }

      var token = ++renderToken;
      if (activeController) activeController.abort();
      activeController =
        typeof AbortController !== "undefined" ? new AbortController() : null;
      var fetchOptions = activeController
        ? { signal: activeController.signal }
        : {};

      fetchFn(resolvedUrl, fetchOptions)
        .then(function (res) {
          if (!res || !res.ok)
            throw new Error("SVG HTTP " + (res ? res.status : "error"));
          return res.text();
        })
        .then(function (text) {
          var safeSvg = sanitizeSvgMarkup(text);
          if (!safeSvg) throw new Error("Invalid SVG");
          svgCache.set(resolvedUrl, safeSvg);
          if (token !== renderToken) return;
          stage.innerHTML = safeSvg;
          currentAvatarKey = resolvedUrl;
          applyColors(lastStatus && lastStatus.avatar_colors);
          applySpeakingState(
            lastStatus
              ? lastStatus.status === "playing" ||
                  lastStatus.phase === "playing"
              : isPlaying,
          );
        })
        .catch(function () {
          if (token !== renderToken) return;
          restoreDefaultAvatar();
          applySpeakingState(
            lastStatus
              ? lastStatus.status === "playing" ||
                  lastStatus.phase === "playing"
              : isPlaying,
          );
        });
    }

    return {
      handleStatus: handleStatus,
      restoreDefaultAvatar: restoreDefaultAvatar,
      getCurrentAvatarKey: function () {
        return currentAvatarKey;
      },
    };
  }

  var stream = null;
  var controller = null;

  function startStreaming() {
    if (stream || typeof document === "undefined") return;
    var base = document.body.dataset.base || "";
    var stage = document.getElementById("pia-stage") || document.body;
    controller = createMiniController({ stage: stage, base: base });

    if (typeof fetch !== "undefined") {
      fetch(base.replace(/\/+$/, "") + "/tts/status")
        .then(function (res) {
          return res.ok ? res.json() : null;
        })
        .then(function (status) {
          if (status) controller.handleStatus(status);
        })
        .catch(function () {});
    }

    stream = new EventSource(base + "/tts/status/stream");
    stream.onmessage = function (event) {
      try {
        controller.handleStatus(JSON.parse(event.data));
      } catch (_err) {}
    };
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = {
      sanitizeSvgMarkup: sanitizeSvgMarkup,
      resolveAvatarUrl: resolveAvatarUrl,
      createMiniController: createMiniController,
    };
  } else if (typeof document !== "undefined") {
    if (document.readyState === "loading") {
      window.addEventListener("DOMContentLoaded", startStreaming);
    } else {
      startStreaming();
    }
  }
})();

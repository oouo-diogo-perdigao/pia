import React, { useEffect, useMemo, useState } from "react";
import { Bot } from "lucide-react";

const svgCache = new Map();
const FORBIDDEN_TAGS = new Set([
  "script",
  "foreignobject",
  "iframe",
  "object",
  "embed",
  "link",
  "meta",
]);

function sanitizeBrowserSvg(raw) {
  if (typeof raw !== "string" || !raw.trim()) return "";
  if (typeof DOMParser === "undefined") return "";
  const doc = new DOMParser().parseFromString(raw.trim(), "image/svg+xml");
  if (!doc || doc.querySelector("parsererror")) return "";
  const root = doc.documentElement;
  if (!root || root.nodeName.toLowerCase() !== "svg") return "";

  const walk = (node) => {
    for (const child of Array.from(node.children || [])) {
      const tag = child.nodeName.toLowerCase();
      if (FORBIDDEN_TAGS.has(tag)) {
        child.remove();
        continue;
      }
      for (const attr of Array.from(child.attributes || [])) {
        const name = attr.name.toLowerCase();
        const val = String(attr.value || "");
        if (
          name.startsWith("on") ||
          /^\s*javascript:/i.test(val) ||
          (name === "style" && /url\s*\(|@import|expression\s*\(/i.test(val)) ||
          (name === "href" && !val.trim().startsWith("#"))
        ) {
          child.removeAttribute(attr.name);
        }
      }
      if (
        tag === "style" &&
        /url\s*\(|@import|expression\s*\(/i.test(child.textContent || "")
      ) {
        child.textContent = "";
      }
      walk(child);
    }
  };

  for (const attr of Array.from(root.attributes || [])) {
    if (attr.name.toLowerCase().startsWith("on")) {
      root.removeAttribute(attr.name);
    }
  }
  walk(root);
  root.setAttribute("width", "100%");
  root.setAttribute("height", "100%");
  return new XMLSerializer().serializeToString(root);
}

export default function SafeSvgAvatar({
  svg = "",
  src = "",
  colors = null,
  size = 48,
  speaking = false,
  alt = "Avatar",
}) {
  const [fetchedSvg, setFetchedSvg] = useState(() =>
    src && svgCache.has(src) ? svgCache.get(src) : "",
  );
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (svg || !src || src === "/pia.svg") {
      setFetchedSvg("");
      setFailed(false);
      return;
    }
    if (svgCache.has(src)) {
      setFetchedSvg(svgCache.get(src));
      setFailed(false);
      return;
    }
    let active = true;
    fetch(src)
      .then((res) => {
        if (!res.ok) throw new Error("SVG load failed");
        return res.text();
      })
      .then((text) => {
        const clean = sanitizeBrowserSvg(text);
        if (!clean) throw new Error("Invalid SVG");
        svgCache.set(src, clean);
        if (active) {
          setFetchedSvg(clean);
          setFailed(false);
        }
      })
      .catch(() => {
        if (active) setFailed(true);
      });
    return () => {
      active = false;
    };
  }, [svg, src]);

  const cleanInline = useMemo(() => {
    const raw = svg || fetchedSvg;
    return raw ? sanitizeBrowserSvg(raw) : "";
  }, [svg, fetchedSvg]);

  const containerRef = React.useRef(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    for (const mouth of el.querySelectorAll(".enable-mouth")) {
      mouth.style.opacity = speaking ? "1" : "0";
    }
    for (const anim of el.querySelectorAll(".animation-talking")) {
      anim.style.animationPlayState = speaking ? "running" : "paused";
    }
  }, [cleanInline, speaking]);

  const styleVars = {
    width: size,
    height: size,
    flexShrink: 0,
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 12,
    overflow: "hidden",
    ...(colors?.primary ? { "--bot-primary": colors.primary } : {}),
    ...(colors?.accent ? { "--bot-accent": colors.accent } : {}),
    ...(colors?.eyes ? { "--bot-eyes": colors.eyes } : {}),
  };

  if (cleanInline) {
    return (
      <div
        ref={containerRef}
        role="img"
        aria-label={alt}
        style={styleVars}
        dangerouslySetInnerHTML={{ __html: cleanInline }}
      />
    );
  }

  if (src && !failed) {
    return (
      <img
        src={src}
        alt={alt}
        width={size}
        height={size}
        style={{
          width: size,
          height: size,
          objectFit: "contain",
          flexShrink: 0,
          borderRadius: 10,
        }}
        onError={() => setFailed(true)}
      />
    );
  }

  return (
    <div style={styleVars}>
      <Bot size={Math.round(size * 0.65)} />
    </div>
  );
}

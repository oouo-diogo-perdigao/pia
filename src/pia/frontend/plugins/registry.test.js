import { describe, it } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import module from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));

module.registerHooks({
  load(url, context, nextLoad) {
    if (url.endsWith(".jsx")) {
      return {
        format: "module",
        shortCircuit: true,
        source: `
          export default function MockPanel() { return null; }
          export function BotEditor() { return null; }
          export function BotRunPanel() { return null; }
          export function SafeSvgAvatar() { return null; }
        `,
      };
    }
    return nextLoad(url, context);
  },
});

const {
  buildPluginRegistry,
  isBuiltinReactPlugin,
  listRegisteredPlugins,
  pluginRegistry,
  resolvePluginPanel,
} = await import("./registry.js");

describe("plugins/registry dynamic & explicit resolution", () => {
  it("resolves every built-in app and bot panel including aliases from real pluginRegistry", () => {
    for (const id of [
      "music",
      "podcast_automation",
      "podcast-automation",
      "screenshots",
      "object_storage",
      "object-storage",
      "secretaria",
    ]) {
      const entry = resolvePluginPanel(id, pluginRegistry);
      assert.ok(entry, `Expected plugin registry entry for ${id}`);
      assert.equal(
        typeof entry.Component,
        "function",
        `Expected React Component for ${id}`,
      );
      assert.equal(isBuiltinReactPlugin(id), true);
    }

    const openbot = resolvePluginPanel("openbot", pluginRegistry);
    assert.ok(openbot);
    assert.equal(typeof openbot.exports?.BotEditor, "function");
    assert.equal(typeof openbot.exports?.BotRunPanel, "function");
    assert.equal(typeof openbot.exports?.SafeSvgAvatar, "function");
    assert.equal(resolvePluginPanel("bots", pluginRegistry), openbot);
  });

  it("never wraps import.meta.glob in typeof import.meta?.glob === function", () => {
    const src = fs.readFileSync(path.join(here, "registry.js"), "utf8");
    assert.equal(src.includes("typeof import.meta?.glob"), false);
    assert.equal(src.includes("typeof import.meta.glob"), false);
  });

  it("indexes nested (Apps/Bot/Connectors) and top-level (OpenBot) plugin panels", () => {
    const MusicPanel = () => "music";
    const SecretariaPanel = () => "secretaria";
    const BotRunPanel = () => "bot-run";
    const SafeSvgAvatar = () => "avatar";

    const registry = buildPluginRegistry({
      "../../../../Plugins/Apps/music/web/Panel.jsx": { default: MusicPanel },
      "../../../../Plugins/Bot/secretaria/web/Panel.jsx": {
        default: SecretariaPanel,
      },
      "../../../../Plugins/OpenBot/web/Panel.jsx": {
        BotRunPanel,
        SafeSvgAvatar,
      },
    });

    assert.equal(listRegisteredPlugins(registry).length, 3);
    assert.equal(resolvePluginPanel("music", registry)?.Component, MusicPanel);
    assert.equal(
      resolvePluginPanel("apps/music", registry)?.Component,
      MusicPanel,
    );
    assert.equal(
      resolvePluginPanel("secretaria", registry)?.Component,
      SecretariaPanel,
    );
    assert.equal(
      resolvePluginPanel("openbot", registry)?.exports?.BotRunPanel,
      BotRunPanel,
    );
    assert.equal(
      resolvePluginPanel("openbot", registry)?.exports?.SafeSvgAvatar,
      SafeSvgAvatar,
    );
    assert.equal(resolvePluginPanel("missing", registry), null);
  });
});

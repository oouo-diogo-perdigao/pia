import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  buildPluginRegistry,
  listRegisteredPlugins,
  resolvePluginPanel,
} from "./registry.js";

describe("plugins/registry dynamic discovery", () => {
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

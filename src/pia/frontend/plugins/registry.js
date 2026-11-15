import MusicPanel from "../../../../Plugins/Apps/music/web/Panel.jsx";
import ObjectStoragePanel from "../../../../Plugins/Apps/object_storage/web/Panel.jsx";
import PodcastAutomationPanel from "../../../../Plugins/Apps/podcast_automation/web/Panel.jsx";
import ScreenshotsPanel from "../../../../Plugins/Apps/screenshots/web/Panel.jsx";
import SecretariaPanel from "../../../../Plugins/Bot/secretaria/web/Panel.jsx";
import * as OpenBotModule from "../../../../Plugins/OpenBot/web/Panel.jsx";

const EXPLICIT_PLUGIN_MODULES = {
  "../../../../Plugins/Apps/music/web/Panel.jsx": { default: MusicPanel },
  "../../../../Plugins/Apps/object_storage/web/Panel.jsx": {
    default: ObjectStoragePanel,
  },
  "../../../../Plugins/Apps/podcast_automation/web/Panel.jsx": {
    default: PodcastAutomationPanel,
  },
  "../../../../Plugins/Apps/screenshots/web/Panel.jsx": {
    default: ScreenshotsPanel,
  },
  "../../../../Plugins/Bot/secretaria/web/Panel.jsx": {
    default: SecretariaPanel,
  },
  "../../../../Plugins/OpenBot/web/Panel.jsx": OpenBotModule,
};

const PLUGIN_ID_ALIASES = {
  "podcast-automation": "podcast_automation",
  "object-storage": "object_storage",
  bots: "openbot",
};

export const BUILTIN_REACT_PLUGIN_IDS = new Set([
  "music",
  "object_storage",
  "object-storage",
  "podcast_automation",
  "podcast-automation",
  "screenshots",
  "secretaria",
  "openbot",
  "bots",
]);

let nestedPanels = {};
try {
  // Always invoke import.meta.glob directly so Vite expands it unconditionally.
  nestedPanels = import.meta.glob("../../../../Plugins/*/*/web/Panel.jsx", {
    eager: true,
  });
} catch {
  nestedPanels = {};
}

let topLevelPanels = {};
try {
  topLevelPanels = import.meta.glob("../../../../Plugins/*/web/Panel.jsx", {
    eager: true,
  });
} catch {
  topLevelPanels = {};
}

function normalizePluginToken(value) {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replace(/\\/g, "/");
}

function parsePluginDescriptor(modulePath, mod) {
  const normalized = normalizePluginToken(modulePath);
  const nestedMatch = normalized.match(
    /\/plugins\/([^/]+)\/([^/]+)\/web\/panel\.jsx$/i,
  );
  if (nestedMatch) {
    const category = nestedMatch[1];
    const id = nestedMatch[2];
    const resolvedMod = mod && typeof mod === "object" ? mod : {};
    return {
      key: `${category}/${id}`,
      id,
      category,
      path: modulePath,
      Component: resolvedMod.default || null,
      exports: resolvedMod,
    };
  }
  const topMatch = normalized.match(/\/plugins\/([^/]+)\/web\/panel\.jsx$/i);
  if (topMatch) {
    const id = topMatch[1];
    const resolvedMod = mod && typeof mod === "object" ? mod : {};
    return {
      key: id,
      id,
      category: id,
      path: modulePath,
      Component: resolvedMod.default || null,
      exports: resolvedMod,
    };
  }
  return null;
}

export function buildPluginRegistry(modulesMap) {
  const byKey = new Map();
  const byId = new Map();
  for (const [path, mod] of Object.entries(modulesMap || {})) {
    const entry = parsePluginDescriptor(path, mod);
    if (!entry) continue;
    byKey.set(entry.key, entry);
    if (!byId.has(entry.id) || entry.Component) {
      byId.set(entry.id, entry);
    }
    const dashed = entry.id.replace(/_/g, "-");
    if (dashed !== entry.id && !byId.has(dashed)) {
      byId.set(dashed, entry);
    }
    const underscored = entry.id.replace(/-/g, "_");
    if (underscored !== entry.id && !byId.has(underscored)) {
      byId.set(underscored, entry);
    }
  }
  return { byKey, byId };
}

export const pluginRegistry = buildPluginRegistry({
  ...EXPLICIT_PLUGIN_MODULES,
  ...nestedPanels,
  ...topLevelPanels,
});

export function isBuiltinReactPlugin(pluginOrId) {
  const raw = normalizePluginToken(pluginOrId);
  if (!raw) return false;
  const shortId = raw.includes("/") ? raw.split("/").pop() : raw;
  return BUILTIN_REACT_PLUGIN_IDS.has(shortId);
}

export function resolvePluginPanel(pluginOrId, registry = pluginRegistry) {
  const raw = normalizePluginToken(pluginOrId);
  if (!raw || !registry) return null;
  if (registry.byKey?.has(raw)) return registry.byKey.get(raw);
  const shortId = raw.includes("/") ? raw.split("/").pop() : raw;
  const aliased = PLUGIN_ID_ALIASES[shortId] || shortId;
  return (
    registry.byId?.get(shortId) ||
    registry.byId?.get(aliased) ||
    registry.byId?.get(shortId.replace(/-/g, "_")) ||
    registry.byId?.get(shortId.replace(/_/g, "-")) ||
    null
  );
}

export function listRegisteredPlugins(registry = pluginRegistry) {
  if (!registry?.byKey) return [];
  return Array.from(registry.byKey.values());
}

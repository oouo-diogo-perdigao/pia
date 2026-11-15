const nestedPanels =
  typeof import.meta?.glob === "function"
    ? import.meta.glob("../../../../Plugins/*/*/web/Panel.jsx", { eager: true })
    : {};

const topLevelPanels =
  typeof import.meta?.glob === "function"
    ? import.meta.glob("../../../../Plugins/*/web/Panel.jsx", { eager: true })
    : {};

function parsePluginDescriptor(modulePath, mod) {
  const normalized = String(modulePath || "").replace(/\\/g, "/");
  const nestedMatch = normalized.match(
    /\/Plugins\/([^/]+)\/([^/]+)\/web\/Panel\.jsx$/i,
  );
  if (nestedMatch) {
    const category = nestedMatch[1];
    const id = nestedMatch[2];
    return {
      key: `${category.toLowerCase()}/${id.toLowerCase()}`,
      id: id.toLowerCase(),
      category: category.toLowerCase(),
      path: modulePath,
      Component: mod?.default || null,
      exports: mod || {},
    };
  }
  const topMatch = normalized.match(/\/Plugins\/([^/]+)\/web\/Panel\.jsx$/i);
  if (topMatch) {
    const id = topMatch[1];
    return {
      key: id.toLowerCase(),
      id: id.toLowerCase(),
      category: id.toLowerCase(),
      path: modulePath,
      Component: mod?.default || null,
      exports: mod || {},
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
    if (!byId.has(entry.id)) {
      byId.set(entry.id, entry);
    }
  }
  return { byKey, byId };
}

export const pluginRegistry = buildPluginRegistry({
  ...nestedPanels,
  ...topLevelPanels,
});

export function resolvePluginPanel(pluginOrId, registry = pluginRegistry) {
  const raw = String(pluginOrId || "")
    .trim()
    .toLowerCase()
    .replace(/\\/g, "/");
  if (!raw || !registry) return null;
  if (registry.byKey?.has(raw)) return registry.byKey.get(raw);
  const shortId = raw.includes("/") ? raw.split("/").pop() : raw;
  return registry.byId?.get(shortId) || null;
}

export function listRegisteredPlugins(registry = pluginRegistry) {
  if (!registry?.byKey) return [];
  return Array.from(registry.byKey.values());
}

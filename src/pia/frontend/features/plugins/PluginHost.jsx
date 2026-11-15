import React from "react";
import { resolvePluginPanel } from "../../plugins/registry";

export default function PluginHost({
  pluginId,
  props = {},
  fallbackUrl,
  title,
}) {
  const entry = resolvePluginPanel(pluginId);
  if (entry?.Component) {
    const PanelComponent = entry.Component;
    return <PanelComponent {...props} />;
  }
  if (fallbackUrl) {
    return <iframe title={title || pluginId || "Plugin"} src={fallbackUrl} />;
  }
  return null;
}

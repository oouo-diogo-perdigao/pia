import React from "react";
import { Alert, Button, Stack, Text } from "@mantine/core";
import {
  isBuiltinReactPlugin,
  resolvePluginPanel,
} from "../../plugins/registry";
import { usePia } from "../../shared";

export default function PluginHost({
  pluginId,
  props = {},
  fallbackUrl,
  title,
}) {
  const { navigate } = usePia();
  const entry = resolvePluginPanel(pluginId);
  if (entry?.Component) {
    const PanelComponent = entry.Component;
    return <PanelComponent {...props} />;
  }
  if (
    fallbackUrl &&
    !isBuiltinReactPlugin(pluginId) &&
    fallbackUrl !== "/" &&
    !String(fallbackUrl).startsWith("/bots/secretaria")
  ) {
    return <iframe title={title || pluginId || "Plugin"} src={fallbackUrl} />;
  }
  return (
    <Alert color="red" title={`Painel indisponível: ${title || pluginId}`}>
      <Stack gap="xs">
        <Text size="sm">
          Não foi possível carregar o componente React do plugin{" "}
          <code>{String(pluginId || "")}</code>.
        </Text>
        <Button
          size="xs"
          variant="light"
          w="fit-content"
          onClick={() => navigate({ view: "chat" })}
        >
          Voltar ao Chat
        </Button>
      </Stack>
    </Alert>
  );
}

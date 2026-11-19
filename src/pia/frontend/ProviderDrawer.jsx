import React from "react";
import { Drawer } from "@mantine/core";
import AgentsPanel from "./AgentsPanel";

export default function ProviderDrawer({
  opened,
  onClose,
  focusProvider = null,
  onUpdated,
}) {
  return (
    <Drawer
      opened={Boolean(opened)}
      onClose={onClose}
      position="right"
      size="md"
      title="Provedores de modelos"
    >
      <AgentsPanel
        compact
        focusProvider={focusProvider}
        onStatusChange={onUpdated}
      />
    </Drawer>
  );
}

import React from "react";
import { Stack, Text } from "@mantine/core";
import SettingsPanel, { Accounts } from "./Settings";
export const connectors = [
  {
    id: "google",
    name: "Google",
    info: "Contas Google para Gmail, Agenda e Drive.",
  },
  { id: "microsoft", name: "Microsoft", info: "Contas Microsoft e OneDrive." },
  {
    id: "object_storage",
    name: "Object Storage",
    info: "S3, R2 e armazenamentos compatíveis.",
  },
  { id: "discord", name: "Discord", info: "Bot, canais e notificações." },
];
export default function Connectors({ connector = "google" }) {
  return (
    <Stack>
      {["google", "microsoft"].includes(connector) ? (
        <Accounts key={connector} providerId={connector} />
      ) : (
        <SettingsPanel key={connector} section={"Connectors/" + connector} />
      )}
    </Stack>
  );
}

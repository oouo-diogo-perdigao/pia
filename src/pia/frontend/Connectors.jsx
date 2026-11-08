import AgentsPanel from "./AgentsPanel";
import React from "react";
import { Anchor, Paper, Stack, Text } from "@mantine/core";
import SettingsPanel from "./Settings";
import { api } from "./api";
export const connectors = [
  {
    id: "pia_server",
    name: "PIA Server",
    info: "Pareamento com o servidor da PIA.",
  },
  {
    id: "agents",
    name: "Agentes externos",
    info: "Codex, Google Antigravity e protocolos de ferramentas.",
  },
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
  {
    id: "taverns",
    name: "Taverns",
    info: "Bot, canais e notificações da Tav.gg.",
  },
];
export default function Connectors({ connector = "google" }) {
  const [server, setServer] = React.useState("https://pia.travelrpg.com");
  React.useEffect(() => {
    if (["agents", "pia_server"].includes(connector)) return;
    let active = true;
    api("/settings").then((sections) => {
      const section = sections.find((entry) => entry.id === "Connectors/pia_server");
      const configured = section?.fields.find((field) => field.name === "PIA_SERVER_URL")?.value;
      if (active && configured?.startsWith("https://")) setServer(configured.replace(/\/$/, ""));
    }).catch(() => {});
    return () => { active = false; };
  }, [connector]);

  if (connector === "agents") return <AgentsPanel />;
  if (connector === "pia_server") return <SettingsPanel section="Connectors/pia_server" />;
  return (
    <Paper withBorder p="lg">
      <Stack>
        <Text>Adicione, edite e remova contas na PIA Server. Os computadores pareados usam o cadastro do servidor.</Text>
        <Anchor href={server + "/#connectors"} target="_blank" rel="noreferrer">
          Gerenciar conectores na PIA Server
        </Anchor>
      </Stack>
    </Paper>
  );
}

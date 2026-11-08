import AgentsPanel from "./AgentsPanel";
import React from "react";
import SettingsPanel from "./Settings";

export const connectors = [
  { id: "pia_server", name: "PIA Server", info: "Preferências deste computador e perfil compartilhado." },
  { id: "agents", name: "Agentes externos", info: "Codex, Google Antigravity e protocolos de ferramentas." },
];

export default function Connectors({ connector }) {
  if (connector === "agents") return <AgentsPanel />;
  return <SettingsPanel section="Connectors/pia_server" />;
}

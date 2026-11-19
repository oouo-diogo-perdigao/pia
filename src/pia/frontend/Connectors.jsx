import AgentsPanel from "./AgentsPanel";
import McpConnectorsPanel from "./McpConnectorsPanel";
import React from "react";
import SettingsPanel from "./Settings";

export const connectors = [
  {
    id: "pia_server",
    name: "PIA Server",
    info: "Preferências deste computador e perfil compartilhado.",
  },
  {
    id: "agents",
    name: "Agentes externos",
    info: "Codex, Google Antigravity e protocolos de ferramentas.",
  },
  {
    id: "mcp",
    name: "Conectores MCP",
    info: "Servidores MCP personalizados (STDIO/HTTP), OAuth e multi-contas.",
  },
];

export default function Connectors({ connector }) {
  if (connector === "agents") return <AgentsPanel />;
  if (connector === "mcp") return <McpConnectorsPanel />;
  return <SettingsPanel section="Connectors/pia_server" />;
}

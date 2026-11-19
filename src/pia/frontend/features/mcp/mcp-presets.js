import {
  createEmptyAccountDraft,
  createEmptyMcpDraft,
} from "../../extensions-helpers.js";

export const MCP_ONE_CLICK_PRESETS = [
  {
    id: "suno",
    label: "Suno",
    badge: "Distribuído",
    description: "Divide requisições entre contas para somar créditos.",
    apply: () => ({
      name: "Suno MCP",
      description: "Geração musical distribuída entre múltiplas contas Suno.",
      transport: "http",
      url: "https://mcp.suno.example.com/mcp",
      bearer_token_env: "SUNO_MCP_TOKEN",
      account_mode: "distributed",
      active_context: "Pessoal",
      accounts: [
        {
          ...createEmptyAccountDraft(1),
          name: "Suno Conta 1",
          context: "Pessoal",
          auth_type: "bearer",
        },
        {
          ...createEmptyAccountDraft(2),
          name: "Suno Conta 2",
          context: "Extra",
          auth_type: "env",
          bearer_env: "SUNO_MCP_TOKEN_2",
        },
      ],
    }),
  },
  {
    id: "dropbox",
    label: "Dropbox",
    badge: "Incremental",
    description: "Consulta todas as contas em conjunto numa única resposta.",
    apply: () => ({
      name: "Dropbox MCP",
      description: "Busca e leitura simultânea em múltiplas contas Dropbox.",
      transport: "http",
      url: "https://mcp.dropbox.com/mcp",
      bearer_token_env: "DROPBOX_MCP_TOKEN",
      account_mode: "incremental",
      active_context: "Trabalho",
      accounts: [
        {
          ...createEmptyAccountDraft(1),
          name: "Dropbox Trabalho",
          context: "Trabalho",
          auth_type: "oauth",
          oauth_auth_url: "https://www.dropbox.com/oauth2/authorize",
          oauth_token_url: "https://api.dropboxapi.com/oauth2/token",
          oauth_scopes: "files.metadata.read files.content.read",
        },
      ],
    }),
  },
  {
    id: "github",
    label: "GitHub",
    badge: "Alternado",
    description:
      "Separa tokens e repositórios por contexto (Trabalho/Pessoal).",
    apply: () => ({
      name: "GitHub MCP",
      description: "Repositórios, issues e PRs separados por contexto.",
      transport: "stdio",
      command: "npx",
      args: "-y @modelcontextprotocol/server-github",
      env: [{ key: "GITHUB_PERSONAL_ACCESS_TOKEN", value: "" }],
      account_mode: "alternating",
      active_context: "Trabalho",
      accounts: [
        {
          ...createEmptyAccountDraft(1),
          name: "GitHub Trabalho",
          context: "Trabalho",
          auth_type: "env",
          bearer_env: "GITHUB_WORK_TOKEN",
        },
        {
          ...createEmptyAccountDraft(2),
          name: "GitHub Pessoal",
          context: "Pessoal",
          auth_type: "env",
          bearer_env: "GITHUB_PERSONAL_TOKEN",
        },
      ],
    }),
  },
  {
    id: "custom",
    label: "Personalizado",
    badge: "Livre",
    description: "Configuração em branco (STDIO ou HTTP com streaming).",
    apply: () => createEmptyMcpDraft(),
  },
];

export function applyMcpPreset(currentDraft, presetId) {
  const base = createEmptyMcpDraft();
  const preset = MCP_ONE_CLICK_PRESETS.find((item) => item.id === presetId);
  if (!preset) return currentDraft || base;
  const patch = preset.apply();
  return {
    ...base,
    ...patch,
    ...(currentDraft?.id ? { id: currentDraft.id } : {}),
  };
}

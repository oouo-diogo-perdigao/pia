import {
  Alert,
  Badge,
  Button,
  Code,
  Group,
  Modal,
  Paper,
  Stack,
  Text,
} from "@mantine/core";
import { ExternalLink, RefreshCw, ShieldCheck, Wrench } from "lucide-react";
import React from "react";
import { safe } from "../../api/client";
import { MCP_ACCOUNT_MODES } from "../../extensions-helpers";

export default function McpToolsModal({
  server,
  tools,
  loading,
  onClose,
  onReinspect,
  onStartAccountOAuth,
}) {
  return (
    <Modal
      opened={!!server}
      onClose={onClose}
      size="lg"
      radius="md"
      title={
        <Group gap="xs">
          <Wrench size={18} />
          <Text fw={700}>
            {server ? `Ferramentas · ${server.name}` : "MCP"}
          </Text>
        </Group>
      }
    >
      {server && (
        <Stack gap="md">
          <Paper p="sm" radius="md" withBorder>
            <Group justify="space-between" wrap="wrap">
              <Stack gap={4}>
                <Group gap="xs">
                  <Badge variant="light" color="blue">
                    {server.transport === "http"
                      ? "HTTP com streaming"
                      : "STDIO"}
                  </Badge>
                  <Badge variant="light" color="teal">
                    {
                      (
                        MCP_ACCOUNT_MODES.find(
                          (m) => m.value === server.account_mode,
                        ) || MCP_ACCOUNT_MODES[2]
                      ).label
                    }
                  </Badge>
                  {server.account_mode === "alternating" && (
                    <Badge variant="outline">
                      Contexto: {server.active_context}
                    </Badge>
                  )}
                </Group>
                <Text size="xs" c="dimmed">
                  {server.transport === "http"
                    ? server.url
                    : [server.command, ...(server.args || [])]
                        .filter(Boolean)
                        .join(" ")}
                </Text>
              </Stack>
              <Button
                size="xs"
                variant="light"
                leftSection={<RefreshCw size={14} />}
                onClick={safe(onReinspect)}
                loading={loading}
              >
                Re-inspecionar servidor
              </Button>
            </Group>
          </Paper>

          {server.accounts.length > 0 && (
            <Paper p="sm" radius="md" withBorder>
              <Text size="sm" fw={600} mb="xs">
                Contas configuradas ({server.accounts.length})
              </Text>
              <Stack gap={6}>
                {server.accounts.map((acc) => (
                  <Group
                    key={acc.id}
                    justify="space-between"
                    align="center"
                    wrap="wrap"
                  >
                    <Group gap="xs">
                      <ShieldCheck size={14} />
                      <Text size="sm" fw={500}>
                        {acc.name}
                      </Text>
                      <Badge size="xs" variant="light">
                        {acc.context}
                      </Badge>
                      <Badge size="xs" variant="outline" color="gray">
                        {acc.auth_type}
                      </Badge>
                    </Group>
                    <Group gap="xs">
                      <Text size="xs" c="dimmed">
                        Uso: {acc.usage_count || 0} req
                      </Text>
                      {acc.auth_type === "oauth" && (
                        <Button
                          size="compact-xs"
                          variant="subtle"
                          leftSection={<ExternalLink size={12} />}
                          onClick={safe(() =>
                            onStartAccountOAuth(server.id, acc, acc.id),
                          )}
                        >
                          OAuth
                        </Button>
                      )}
                    </Group>
                  </Group>
                ))}
              </Stack>
            </Paper>
          )}

          <Stack gap="xs">
            <Group justify="space-between">
              <Text size="sm" fw={600}>
                Ferramentas expostas ({tools.length})
              </Text>
              {loading && (
                <Text size="xs" c="dimmed">
                  Inspecionando…
                </Text>
              )}
            </Group>

            {tools.length === 0 && !loading ? (
              <Alert color="gray" variant="light">
                Nenhuma ferramenta listada ainda. Clique em{" "}
                <strong>Re-inspecionar servidor</strong> para consultar{" "}
                <Code>tools/list</Code> no servidor MCP.
              </Alert>
            ) : (
              tools.map((tool) => (
                <Paper
                  key={tool.name}
                  p="sm"
                  radius="sm"
                  withBorder
                  className="mcp-tool-card"
                >
                  <Group justify="space-between" align="center" mb={4}>
                    <Code fw={600}>{tool.name}</Code>
                  </Group>
                  <Text size="xs" c="dimmed" mb={tool.inputSchema ? 6 : 0}>
                    {tool.description}
                  </Text>
                  {tool.inputSchema && (
                    <Code block className="mcp-tool-schema">
                      {JSON.stringify(tool.inputSchema, null, 2)}
                    </Code>
                  )}
                </Paper>
              ))
            )}
          </Stack>
        </Stack>
      )}
    </Modal>
  );
}

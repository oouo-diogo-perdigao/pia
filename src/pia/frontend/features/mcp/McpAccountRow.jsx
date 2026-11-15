import {
  ActionIcon,
  Button,
  Group,
  Paper,
  PasswordInput,
  Select,
  Stack,
  TextInput,
} from "@mantine/core";
import { KeyRound, Trash2 } from "lucide-react";
import React from "react";
import { safe } from "../../api/client";
import { MCP_ACCOUNT_AUTH_TYPES } from "../../extensions-helpers";

export default function McpAccountRow({
  account,
  index,
  oauthBusy,
  onChange,
  onRemove,
  onStartOAuth,
}) {
  return (
    <Paper p="sm" radius="sm" withBorder className="mcp-account-item">
      <Stack gap="xs">
        <Group justify="space-between" wrap="nowrap">
          <Group gap="xs" style={{ flex: 1 }}>
            <TextInput
              size="xs"
              placeholder="Nome da conta (ex.: Suno 1)"
              value={account.name}
              onChange={(event) =>
                onChange(index, "name", event.currentTarget.value)
              }
              style={{ flex: 1 }}
            />
            <TextInput
              size="xs"
              placeholder="Contexto (ex.: Trabalho)"
              value={account.context}
              onChange={(event) =>
                onChange(index, "context", event.currentTarget.value)
              }
              style={{ flex: 1 }}
            />
            <Select
              size="xs"
              w={150}
              data={MCP_ACCOUNT_AUTH_TYPES}
              value={account.auth_type}
              onChange={(value) =>
                onChange(index, "auth_type", value || "bearer")
              }
            />
          </Group>
          <ActionIcon
            variant="subtle"
            color="red"
            aria-label="Remover conta"
            onClick={() => onRemove(index)}
          >
            <Trash2 size={15} />
          </ActionIcon>
        </Group>

        {account.auth_type === "bearer" && (
          <PasswordInput
            size="xs"
            placeholder="Token / API Key desta conta"
            value={account.bearer_token}
            onChange={(event) =>
              onChange(index, "bearer_token", event.currentTarget.value)
            }
          />
        )}

        {account.auth_type === "env" && (
          <TextInput
            size="xs"
            placeholder="Nome da variável de ambiente (ex.: SUNO_TOKEN_2)"
            value={account.bearer_env}
            onChange={(event) =>
              onChange(index, "bearer_env", event.currentTarget.value)
            }
          />
        )}

        {account.auth_type === "oauth" && (
          <Stack gap="xs">
            <Group grow>
              <TextInput
                size="xs"
                placeholder="OAuth Client ID"
                value={account.oauth_client_id}
                onChange={(event) =>
                  onChange(index, "oauth_client_id", event.currentTarget.value)
                }
              />
              <PasswordInput
                size="xs"
                placeholder="OAuth Client Secret"
                value={account.oauth_client_secret}
                onChange={(event) =>
                  onChange(
                    index,
                    "oauth_client_secret",
                    event.currentTarget.value,
                  )
                }
              />
            </Group>
            <Group grow>
              <TextInput
                size="xs"
                placeholder="Authorization URL"
                value={account.oauth_auth_url}
                onChange={(event) =>
                  onChange(index, "oauth_auth_url", event.currentTarget.value)
                }
              />
              <TextInput
                size="xs"
                placeholder="Token URL"
                value={account.oauth_token_url}
                onChange={(event) =>
                  onChange(index, "oauth_token_url", event.currentTarget.value)
                }
              />
            </Group>
            <Group justify="space-between" wrap="nowrap">
              <TextInput
                size="xs"
                placeholder="Scopes (ex.: read write files.metadata.read)"
                value={account.oauth_scopes}
                onChange={(event) =>
                  onChange(index, "oauth_scopes", event.currentTarget.value)
                }
                style={{ flex: 1 }}
              />
              <Button
                size="xs"
                variant="light"
                leftSection={<KeyRound size={13} />}
                loading={oauthBusy}
                onClick={safe(() => onStartOAuth(account, index))}
              >
                {account.oauth_connected
                  ? "Reconectar OAuth"
                  : "Conectar via OAuth"}
              </Button>
            </Group>
          </Stack>
        )}
      </Stack>
    </Paper>
  );
}

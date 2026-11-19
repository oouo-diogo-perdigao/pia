import {
  ActionIcon,
  Badge,
  Divider,
  Group,
  Popover,
  Stack,
  Text,
} from "@mantine/core";
import { Info, Users } from "lucide-react";
import React from "react";

export function McpUsageBadge({ info }) {
  if (!info?.mcpBadge) return null;
  return (
    <Badge
      size="xs"
      variant="light"
      color="teal"
      leftSection={<Users size={11} />}
      className="chat-mcp-account-badge"
    >
      {info.mcpBadge}
    </Badge>
  );
}

export default function MessageInfoPopover({
  info,
  opened,
  onChange,
  onToggle,
  t,
}) {
  return (
    <Popover
      opened={opened}
      onChange={onChange}
      width={300}
      position="top"
      withArrow
      shadow="md"
    >
      <Popover.Target>
        <ActionIcon
          aria-label={t("Informações do modelo e ferramentas")}
          variant="subtle"
          color="gray"
          onClick={onToggle}
          onMouseEnter={() => onChange(true)}
          onMouseLeave={() => onChange(false)}
        >
          <Info size={17} />
        </ActionIcon>
      </Popover.Target>
      <Popover.Dropdown
        onMouseEnter={() => onChange(true)}
        onMouseLeave={() => onChange(false)}
      >
        <Stack gap={6}>
          <Text size="xs" fw={600}>
            {t("Detalhes da resposta")}
          </Text>
          <Text size="xs" c="dimmed">
            {t("Modelo")}: {info.modelDisplay || t("Padrão do sistema")}
          </Text>
          {info.mcpBadge && (
            <>
              <Divider />
              <Text size="xs" fw={600}>
                {t("Conta / Modo MCP")}
              </Text>
              <McpUsageBadge info={info} />
            </>
          )}
          {info.tools.length > 0 && (
            <>
              <Divider />
              <Text size="xs" fw={600}>
                {t("Ferramentas / MCPs")}
              </Text>
              <Group gap={4}>
                {info.tools.map((tool) => (
                  <Badge
                    key={tool.name}
                    size="xs"
                    variant="light"
                    color="violet"
                  >
                    {tool.detail ? `${tool.name} (${tool.detail})` : tool.name}
                  </Badge>
                ))}
              </Group>
            </>
          )}
        </Stack>
      </Popover.Dropdown>
    </Popover>
  );
}

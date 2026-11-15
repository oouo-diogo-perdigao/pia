import { Badge, Group, Paper, Stack, Text } from "@mantine/core";
import { Sparkles } from "lucide-react";
import React from "react";
import { MCP_ONE_CLICK_PRESETS } from "./mcp-presets";

export default function McpPresetsBar({ activePreset, onSelectPreset }) {
  return (
    <Paper className="mcp-form-box" p="sm" radius="md" withBorder>
      <Stack gap="xs">
        <Group gap={6}>
          <Sparkles size={14} />
          <Text size="xs" fw={600} c="dimmed">
            Modelos rápidos (preenchimento em 1 clique)
          </Text>
        </Group>
        <div className="mcp-presets-grid">
          {MCP_ONE_CLICK_PRESETS.map((preset) => {
            const active = activePreset === preset.id;
            return (
              <button
                key={preset.id}
                type="button"
                className={"mcp-preset-btn" + (active ? " active" : "")}
                onClick={() => onSelectPreset?.(preset.id)}
              >
                <Group justify="space-between" gap={4} wrap="nowrap">
                  <Text size="xs" fw={600}>
                    {preset.label}
                  </Text>
                  <Badge
                    size="xs"
                    variant="light"
                    color={active ? "violet" : "gray"}
                  >
                    {preset.badge}
                  </Badge>
                </Group>
                <Text size="xs" c="dimmed" ta="left" lineClamp={2}>
                  {preset.description}
                </Text>
              </button>
            );
          })}
        </div>
      </Stack>
    </Paper>
  );
}

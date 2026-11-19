import {
  ActionIcon,
  Button,
  Group,
  Paper,
  Stack,
  Text,
  TextInput,
  Tooltip,
} from "@mantine/core";
import { Plus, Trash2 } from "lucide-react";
import React from "react";

export default function PairListSection({
  title,
  pairs,
  onChange,
  addLabel,
  keyPlaceholder = "Chave",
  valuePlaceholder = "Valor",
}) {
  function updateRow(index, field, value) {
    const next = pairs.map((row, idx) =>
      idx === index ? { ...row, [field]: value } : row,
    );
    onChange(next);
  }

  function removeRow(index) {
    const filtered = pairs.filter((_, idx) => idx !== index);
    onChange(filtered.length ? filtered : [{ key: "", value: "" }]);
  }

  function addRow() {
    onChange([...pairs, { key: "", value: "" }]);
  }

  return (
    <Paper className="mcp-form-box" p="md" radius="md" withBorder>
      <Stack gap="xs">
        <Text size="sm" fw={600}>
          {title}
        </Text>
        {pairs.map((row, index) => (
          <Group key={index} gap="xs" wrap="nowrap" align="center">
            <TextInput
              placeholder={keyPlaceholder}
              value={row.key}
              onChange={(event) =>
                updateRow(index, "key", event.currentTarget.value)
              }
              style={{ flex: 1 }}
            />
            <TextInput
              placeholder={valuePlaceholder}
              value={row.value}
              onChange={(event) =>
                updateRow(index, "value", event.currentTarget.value)
              }
              style={{ flex: 1 }}
            />
            <Tooltip label="Remover linha">
              <ActionIcon
                variant="subtle"
                color="gray"
                aria-label="Remover linha"
                onClick={() => removeRow(index)}
              >
                <Trash2 size={16} />
              </ActionIcon>
            </Tooltip>
          </Group>
        ))}
        <Button
          variant="light"
          color="gray"
          size="xs"
          fullWidth
          leftSection={<Plus size={14} />}
          onClick={addRow}
        >
          {addLabel}
        </Button>
      </Stack>
    </Paper>
  );
}

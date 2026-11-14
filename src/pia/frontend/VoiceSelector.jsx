import React, { useEffect, useState } from "react";
import { Select, Loader, Text, Badge, Group, Paper, Stack } from "@mantine/core";
import { api } from "./api";
import { report, safe } from "./api";

function encode(provider, voice) {
  return `${provider}::${voice}`;
}
function decode(value) {
  const idx = value.indexOf("::");
  if (idx < 0) return { provider: value, voice: "" };
  return { provider: value.slice(0, idx), voice: value.slice(idx + 2) };
}

export default function VoiceSelector({ value, onChange }) {
  const [loading, setLoading] = useState(true);
  const [providers, setProviders] = useState([]);
  const [selected, setSelected] = useState(value || "");

  useEffect(() => {
    let active = true;
    fetch("/v1/tts/providers")
      .then((r) => r.json())
      .then((result) => {
        if (!active) return;
        setProviders(result.providers || []);
      })
      .catch(report)
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, []);

  // Sync external value
  useEffect(() => {
    if (value !== undefined) setSelected(value);
  }, [value]);

  const data = providers.map((p) => ({
    group: p.kind === "local" ? "Local" : "Remoto",
    items: (p.voices || []).map((v) => ({
      value: encode(p.id, v.id),
      label: `${p.name} — ${v.name}${p.available ? "" : " (indisponível)"}`,
      disabled: !p.available,
    })),
  }));

  // Flatten providers with no voices (still show status)
  const flat = providers.filter((p) => !(p.voices || []).length);

  async function handleChange(val) {
    setSelected(val);
    const { provider, voice } = decode(val);
    try {
      await fetch("/v1/tts/select", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider, voice }),
      });
      onChange?.(val);
    } catch (e) {
      report(e);
    }
  }

  if (loading) return <Loader size="sm" />;

  return (
    <Stack gap="xs">
      <Group gap="xs">
        <Text size="sm" fw={600}>
          Voz / TTS
        </Text>
        {providers.map((p) => (
          <Badge
            key={p.id}
            color={p.available ? "green" : "gray"}
            variant="light"
            size="xs"
          >
            {p.name}: {p.available ? "disponível" : "sem chave"}
          </Badge>
        ))}
      </Group>
      <Select
        placeholder="Selecione a voz"
        data={data}
        value={selected || null}
        onChange={safe(handleChange)}
        searchable
        nothingFoundMessage="Nenhuma voz disponível"
      />
      {flat.length > 0 && (
        <Text size="xs" c="dimmed">
          Providers sem vozes listadas: {flat.map((p) => p.name).join(", ")}
        </Text>
      )}
    </Stack>
  );
}
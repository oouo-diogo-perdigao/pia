import {
  Badge,
  Button,
  Group,
  Modal,
  Paper,
  Stack,
  Switch,
  Text,
  TextInput,
} from "@mantine/core";
import { Puzzle, RefreshCw, Search, Settings2 } from "lucide-react";
import React, { useEffect, useMemo, useState } from "react";
import { safe } from "../../api/client";
import { pluginsApi } from "../../api/endpoints";
import { usePia } from "../../components/ui";
import { filterPlugins, normalizePlugins } from "../../extensions-helpers";
import { notify } from "../../toasts";

export default function PluginsPanel() {
  const { navigate, refresh: refreshWorkspace } = usePia();
  const [plugins, setPlugins] = useState([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [selectedPlugin, setSelectedPlugin] = useState(null);

  async function loadPlugins() {
    setLoading(true);
    try {
      const response = await pluginsApi.list();
      setPlugins(normalizePlugins(response));
    } catch {
      setPlugins([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadPlugins();
  }, []);

  const visible = useMemo(
    () => filterPlugins(plugins, query),
    [plugins, query],
  );

  async function handleToggle(plugin) {
    const nextEnabled = !plugin.enabled;
    await pluginsApi.toggle(plugin.id, nextEnabled);
    await loadPlugins();
    refreshWorkspace?.();
    notify(`${plugin.name} ${nextEnabled ? "ativado" : "desativado"}.`);
  }

  return (
    <div className="panel">
      <Group justify="space-between" align="flex-start" wrap="wrap">
        <div>
          <Text size="xl" fw={700}>
            Plugins da PIA
          </Text>
          <Text size="sm" c="dimmed">
            Gerencie os plugins nativos e extensões modulares (Automação de
            Podcast, Suno / Música, Geração de Imagens, Secretária, OpenBot).
          </Text>
        </div>
        <Button
          variant="light"
          color="gray"
          leftSection={<RefreshCw size={15} />}
          onClick={safe(loadPlugins)}
          loading={loading}
        >
          Atualizar
        </Button>
      </Group>

      <TextInput
        placeholder="Buscar plugin por nome, categoria ou capacidade…"
        leftSection={<Search size={15} />}
        value={query}
        onChange={(event) => setQuery(event.currentTarget.value)}
      />

      {loading && plugins.length === 0 ? (
        <Text c="dimmed">Carregando plugins…</Text>
      ) : visible.length === 0 ? (
        <Paper p="xl" radius="md" withBorder>
          <Stack align="center" gap="xs">
            <Puzzle size={26} />
            <Text fw={600}>Nenhum plugin encontrado</Text>
            <Text size="sm" c="dimmed">
              Ajuste o termo de busca ou recarregue o catálogo.
            </Text>
          </Stack>
        </Paper>
      ) : (
        <Stack gap="sm">
          {visible.map((plugin) => (
            <Paper
              key={plugin.id}
              p="md"
              radius="md"
              withBorder
              className="extension-card"
            >
              <Group justify="space-between" align="flex-start" wrap="wrap">
                <Stack gap={6} style={{ flex: 1, minWidth: 260 }}>
                  <Group gap="xs" wrap="wrap">
                    <Text fw={600} size="md">
                      {plugin.name}
                    </Text>
                    <Badge size="sm" variant="light" color="gray">
                      v{plugin.version}
                    </Badge>
                    <Badge size="sm" variant="light" color="indigo">
                      {plugin.category}
                    </Badge>
                    <Badge
                      size="sm"
                      variant="dot"
                      color={plugin.enabled ? "green" : "gray"}
                    >
                      {plugin.enabled ? "Ativo" : "Desativado"}
                    </Badge>
                  </Group>

                  {plugin.description && (
                    <Text size="sm" c="dimmed">
                      {plugin.description}
                    </Text>
                  )}

                  {plugin.capabilities.length > 0 && (
                    <Group gap={6} wrap="wrap">
                      {plugin.capabilities.map((cap) => (
                        <Badge
                          key={cap}
                          size="xs"
                          variant="outline"
                          color="gray"
                        >
                          {cap}
                        </Badge>
                      ))}
                    </Group>
                  )}
                </Stack>

                <Group gap="xs" align="center">
                  <Button
                    size="xs"
                    variant="subtle"
                    onClick={() => setSelectedPlugin(plugin)}
                  >
                    Detalhes
                  </Button>
                  {plugin.settings_section && (
                    <Button
                      size="xs"
                      variant="light"
                      leftSection={<Settings2 size={14} />}
                      onClick={() =>
                        navigate({
                          view: "settings",
                          section: plugin.settings_section,
                        })
                      }
                    >
                      Configurar
                    </Button>
                  )}
                  <Switch
                    checked={plugin.enabled}
                    onChange={safe(() => handleToggle(plugin))}
                    aria-label={`Alternar plugin ${plugin.name}`}
                  />
                </Group>
              </Group>
            </Paper>
          ))}
        </Stack>
      )}

      <Modal
        opened={!!selectedPlugin}
        onClose={() => setSelectedPlugin(null)}
        title={selectedPlugin ? selectedPlugin.name : "Detalhes do plugin"}
      >
        {selectedPlugin && (
          <Stack gap="sm">
            <Group gap="xs">
              <Badge variant="light">v{selectedPlugin.version}</Badge>
              <Badge variant="light" color="indigo">
                {selectedPlugin.category}
              </Badge>
              <Badge
                variant="dot"
                color={selectedPlugin.enabled ? "green" : "gray"}
              >
                {selectedPlugin.enabled ? "Ativo" : "Desativado"}
              </Badge>
            </Group>
            <Text size="sm">
              {selectedPlugin.description || "Sem descrição adicional."}
            </Text>
            {selectedPlugin.capabilities.length > 0 && (
              <div>
                <Text size="xs" fw={600} c="dimmed" mb={4}>
                  Capacidades registradas
                </Text>
                <Group gap={6} wrap="wrap">
                  {selectedPlugin.capabilities.map((cap) => (
                    <Badge key={cap} size="sm" variant="outline">
                      {cap}
                    </Badge>
                  ))}
                </Group>
              </div>
            )}
          </Stack>
        )}
      </Modal>
    </div>
  );
}

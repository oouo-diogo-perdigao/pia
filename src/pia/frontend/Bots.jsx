import React, { useEffect, useState } from "react";
import {
  Badge,
  Button,
  Divider,
  Group,
  Modal,
  Paper,
  SimpleGrid,
  Stack,
  Text,
} from "@mantine/core";
import { Bot, Plus, Settings, Sparkles } from "lucide-react";
import { usePia } from "./shared";
import NotificationMenu, { CountBadge } from "./NotificationMenu";
import {
  BotEditor,
  SafeSvgAvatar,
} from "../../../Plugins/OpenBot/web/Panel.jsx";

function voiceLabel(voice) {
  if (voice?.mode === "custom" && voice?.profile) {
    return `Voz própria · ${voice.profile.voice || voice.profile.provider}`;
  }
  return "Voz Geral da PIA";
}

export default function Bots() {
  const { state, route, navigate } = usePia();
  const [createOpen, setCreateOpen] = useState(false);

  useEffect(() => {
    if (route?.create) {
      setCreateOpen(true);
    }
  }, [route?.create]);

  const bots = state.bots || [];
  const nativeBots = bots.filter((b) => b.kind !== "dynamic");
  const dynamicBots = bots.filter((b) => b.kind === "dynamic");

  return (
    <Stack gap="lg">
      <Group justify="space-between" align="center" wrap="wrap" gap="sm">
        <Stack gap={2}>
          <Text fw={700} size="lg">
            Central de Bots
          </Text>
          <Text size="sm" c="dimmed">
            Gerencie bots nativos e crie bots dinâmicos com instruções, voz e
            avatar personalizados.
          </Text>
        </Stack>
        <Button
          leftSection={<Plus size={16} />}
          onClick={() => setCreateOpen(true)}
        >
          Criar Bot Dinâmico
        </Button>
      </Group>

      <Divider label="Bots Nativos" labelPosition="left" />
      <SimpleGrid cols={{ base: 1, sm: 2 }}>
        {nativeBots.map((bot) => (
          <NotificationMenu key={bot.id} source={"Bot/" + bot.id}>
            <Paper withBorder p="lg" className="bot-card">
              <CountBadge
                count={state.notifications?.counts?.["Bot/" + bot.id]}
              />
              <Group justify="space-between" align="flex-start" wrap="nowrap">
                <Group>
                  {bot.avatar ? (
                    <img src={bot.avatar} alt="" width="48" height="48" />
                  ) : (
                    <Bot />
                  )}
                  <Stack gap={2}>
                    <Group gap="xs">
                      <Text fw={600}>{bot.name}</Text>
                      <Badge size="xs" variant="light" color="gray">
                        Nativo
                      </Badge>
                    </Group>
                    <Badge size="xs" variant="dot" color="violet">
                      {voiceLabel(bot.voice)}
                    </Badge>
                  </Stack>
                </Group>
              </Group>
              <Text size="sm" c="dimmed" my="sm">
                {bot.description}
              </Text>
              <Button
                variant="light"
                onClick={() => navigate({ view: "bots", bot: bot.id })}
              >
                Abrir {bot.name}
              </Button>
            </Paper>
          </NotificationMenu>
        ))}
      </SimpleGrid>

      <Divider label="Bots Dinâmicos · OpenBot" labelPosition="left" />
      {!dynamicBots.length ? (
        <Paper withBorder p="xl" radius="md">
          <Stack align="center" gap="sm">
            <Sparkles size={28} />
            <Text fw={600}>Nenhum bot dinâmico criado ainda</Text>
            <Text size="sm" c="dimmed" ta="center" maw={440}>
              Crie agentes especializados com instruções próprias (AGENTS.md),
              avatar SVG animado no PIA Mini e voz independente.
            </Text>
            <Button
              leftSection={<Plus size={16} />}
              onClick={() => setCreateOpen(true)}
            >
              Criar primeiro bot dinâmico
            </Button>
          </Stack>
        </Paper>
      ) : (
        <SimpleGrid cols={{ base: 1, sm: 2 }}>
          {dynamicBots.map((bot) => (
            <NotificationMenu key={bot.id} source={"Bot/" + bot.id}>
              <Paper withBorder p="lg" className="bot-card">
                <CountBadge
                  count={state.notifications?.counts?.["Bot/" + bot.id]}
                />
                <Group justify="space-between" align="flex-start" wrap="nowrap">
                  <Group wrap="nowrap">
                    <SafeSvgAvatar
                      src={bot.avatar_url || bot.avatar}
                      colors={bot.avatar_colors}
                      size={48}
                      alt={bot.name}
                    />
                    <Stack gap={3}>
                      <Group gap="xs" wrap="wrap">
                        <Text fw={600}>{bot.name}</Text>
                        <Badge
                          size="xs"
                          variant="light"
                          color={bot.enabled !== false ? "green" : "gray"}
                        >
                          {bot.enabled !== false ? "Ativo" : "Desativado"}
                        </Badge>
                      </Group>
                      <Badge size="xs" variant="dot" color="violet">
                        {voiceLabel(bot.voice)}
                      </Badge>
                    </Stack>
                  </Group>
                </Group>
                <Text size="sm" c="dimmed" my="sm" lineClamp={2}>
                  {bot.description || "Sem descrição."}
                </Text>
                <Group gap="xs">
                  <Button
                    variant="light"
                    onClick={() => navigate({ view: "bots", bot: bot.id })}
                  >
                    Conversar / Executar
                  </Button>
                  <Button
                    variant="subtle"
                    size="xs"
                    leftSection={<Settings size={14} />}
                    onClick={() =>
                      navigate({ view: "bots", bot: bot.id, tab: "config" })
                    }
                  >
                    Configurar
                  </Button>
                </Group>
              </Paper>
            </NotificationMenu>
          ))}
        </SimpleGrid>
      )}

      <Modal
        opened={createOpen}
        onClose={() => setCreateOpen(false)}
        title="Criar Bot Dinâmico (OpenBot)"
        size="xl"
      >
        <BotEditor
          allBots={bots}
          onCancel={() => setCreateOpen(false)}
          onSaved={(savedBot) => {
            setCreateOpen(false);
            navigate({ view: "bots", bot: savedBot.id });
          }}
        />
      </Modal>
    </Stack>
  );
}

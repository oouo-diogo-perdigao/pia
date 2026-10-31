import React from "react";
import { SimpleGrid, Paper, Text, Button, Group } from "@mantine/core";
import { Bot } from "lucide-react";
import { usePia } from "./shared";
import NotificationMenu, { CountBadge } from "./NotificationMenu";
export default function Bots() {
  const { state, navigate } = usePia();
  return (
    <SimpleGrid cols={{ base: 1, sm: 2 }}>
      {(state.bots || []).map((bot) => (
        <NotificationMenu key={bot.id} source={"Bot/" + bot.id}>
          <Paper withBorder p="lg" className="bot-card">
            <CountBadge
              count={state.notifications?.counts?.["Bot/" + bot.id]}
            />
            <Group>
              {bot.avatar ? (
                <img src={bot.avatar} alt="" width="48" height="48" />
              ) : (
                <Bot />
              )}
              <Text fw={600}>{bot.name}</Text>
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
  );
}

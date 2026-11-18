import React, { useEffect, useState } from "react";
import { Button, Group, Modal, Stack, Text } from "@mantine/core";
import { api } from "./api";
import { notifyMusicProvidersUpdated } from "./music-helpers";
import {
  SUNO_LEGACY_DISMISS_LABEL,
  SUNO_LEGACY_QUESTION,
  SUNO_LEGACY_REMOVE_LABEL,
  describeSunoError,
  legacyCredentialsState,
} from "./music-suno-helpers";
import { notify } from "./toasts";

// RN21/CA20: no primeiro início da versão nova, se o item suno_mcp do
// /music/providers trouxer legacy_credentials {present, prompt: true},
// pergunta se remove as credenciais antigas do Suno deste computador.
// Nunca apaga nada sem o clique em "Remover"; "Agora não" só chama o dismiss.
export default function SunoLegacyPrompt() {
  const [opened, setOpened] = useState(false);
  const [busy, setBusy] = useState("");

  useEffect(() => {
    let alive = true;
    api("/music/providers")
      .then((catalog) => {
        if (alive && legacyCredentialsState(catalog).prompt) setOpened(true);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  async function answer(action) {
    setBusy(action);
    try {
      if (action === "remove") {
        const result = await api("/music/suno/legacy-credentials/remove", {
          confirm: true,
        });
        const removed = Array.isArray(result?.removed) ? result.removed : [];
        notify(
          removed.length
            ? "Credenciais antigas do Suno removidas: " +
                removed.join(", ") +
                "."
            : "Credenciais antigas do Suno removidas.",
        );
      } else {
        await api("/music/suno/legacy-credentials/dismiss", {});
      }
      setOpened(false);
      notifyMusicProvidersUpdated();
    } catch (error) {
      notify(describeSunoError(error).text, "error");
    } finally {
      setBusy("");
    }
  }

  return (
    <Modal
      opened={opened}
      onClose={() => !busy && setOpened(false)}
      title="Suno"
      closeOnClickOutside={false}
    >
      <Stack>
        <Text size="sm">{SUNO_LEGACY_QUESTION}</Text>
        <Group justify="flex-end">
          <Button
            variant="default"
            loading={busy === "dismiss"}
            disabled={Boolean(busy)}
            onClick={() => answer("dismiss")}
          >
            {SUNO_LEGACY_DISMISS_LABEL}
          </Button>
          <Button
            color="red"
            loading={busy === "remove"}
            disabled={Boolean(busy)}
            onClick={() => answer("remove")}
          >
            {SUNO_LEGACY_REMOVE_LABEL}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

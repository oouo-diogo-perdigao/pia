import React, { useEffect, useState } from "react";
import { Anchor, Button, Paper, Stack, Text, TextInput, Title } from "@mantine/core";
import { api } from "./api";

export default function ServerLogin({ server }) {
  const [address, setAddress] = useState(server);
  const [attempt, setAttempt] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function begin(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      setAttempt(await api("/integrations/pia_server/login-start", { server: address.trim() }));
    } catch (problem) {
      setError(problem.message);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (!attempt) return;
    let active = true;
    let timer;
    async function check() {
      try {
        const result = await api("/integrations/pia_server/login-poll", { id: attempt.id });
        if (!active) return;
        if (result.status === "authorized") {
          location.reload();
          return;
        }
        if (result.status === "expired") {
          setAttempt(null);
          setError("O pedido de login expirou. Inicie novamente.");
          return;
        }
        setError("");
      } catch (problem) {
        if (!active) return;
        setError(problem.message);
      }
      if (active) timer = setTimeout(check, 3000);
    }
    timer = setTimeout(check, 1500);
    return () => { active = false; clearTimeout(timer); };
  }, [attempt]);

  return (
    <main className="loading-screen">
      <Paper withBorder p="xl" radius="lg" w="min(25rem, 90vw)">
        <Stack gap="md">
          <Title order={2}>Entrar na PIA</Title>
          {attempt ? (
            <>
              <Text>Abra o navegador, confira o código e autorize este computador com sua conta Google.</Text>
              <Text fw={700} size="xl" aria-label="Código de autorização">{attempt.code}</Text>
              <Button component={Anchor} href={attempt.url} target="_blank" rel="noreferrer">Abrir login no navegador</Button>
              <Text size="sm" role="status">Aguardando autorização…</Text>
              <Button variant="subtle" onClick={() => { setAttempt(null); setError(""); }}>Cancelar</Button>
            </>
          ) : (
            <form onSubmit={begin}>
              <Stack gap="md">
                <Text>Conecte este computador à sua conta na PIA Server.</Text>
                <TextInput label="PIA Server" type="url" required value={address} onChange={(event) => setAddress(event.currentTarget.value)} />
                <Button type="submit" loading={busy}>Continuar com Google</Button>
              </Stack>
            </form>
          )}
          {error && <Text c="red" role="alert">{error}</Text>}
        </Stack>
      </Paper>
    </main>
  );
}

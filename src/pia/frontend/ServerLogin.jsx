import React, { useEffect, useState } from "react";
import { Anchor, Button, Stack, Text, TextInput } from "@mantine/core";
import { api } from "./api";
import "./login.css";

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
    <main className="pia-login">
      <section className="pia-login-card" aria-labelledby="login-title">
        <img className="pia-login-logo" src="/pia/brand.svg" alt="" width="64" height="64" />
        <h2 id="login-title">Entrar na PIA</h2>
        {attempt ? (
          <Stack align="center">
            <Text>Confira o código abaixo ao autorizar este computador no navegador.</Text>
            <strong className="pia-login-code" aria-label="Código de autorização">{attempt.code}</strong>
            <Button component={Anchor} href={attempt.url} target="_blank" rel="noreferrer">
              Abrir login no navegador
            </Button>
            <Text size="sm" role="status">Aguardando autorização…</Text>
            <Button variant="subtle" onClick={() => { setAttempt(null); setError(""); }}>Cancelar</Button>
          </Stack>
        ) : (
          <form onSubmit={begin}>
            <p>Entre para conectar este computador à sua conta na PIA Server.</p>
            <button className="google-signin" type="submit" disabled={busy}>
              <img src="/pia/google-signin.png" alt="" />
              Continuar com Google
            </button>
            <details className="pia-login-options">
              <summary>Usar outro servidor</summary>
              <TextInput label="Endereço da PIA Server" type="url" required value={address}
                onChange={(event) => setAddress(event.currentTarget.value)} />
            </details>
          </form>
        )}
        {error && <Text mt="md" c="red" role="alert">{error}</Text>}
      </section>
    </main>
  );
}

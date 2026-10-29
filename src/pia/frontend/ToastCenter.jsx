import React, { useState, useEffect } from "react";
import { Alert, Modal, Stack, Text, Group, Button } from "@mantine/core";
import { toastHistory } from "./toasts";
import { copy, safe } from "./api";
export default function ToastCenter() {
  const [entry, setEntry] = useState(null),
    [opened, setOpened] = useState(false),
    [history, setHistory] = useState([]);
  useEffect(() => {
    let timer;
    const receive = (event) => {
      if (event.detail.type !== "error") setEntry(event.detail);
      clearTimeout(timer);
      timer = setTimeout(() => setEntry(null), 6000);
      setHistory(toastHistory());
    };
    const show = () => {
      setHistory(toastHistory());
      setOpened(true);
    };
    window.addEventListener("pia:toast", receive);
    window.addEventListener("pia:toast-history", show);
    return () => {
      clearTimeout(timer);
      window.removeEventListener("pia:toast", receive);
      window.removeEventListener("pia:toast-history", show);
    };
  }, []);
  return (
    <>
      {entry && (
        <Alert
          className="success-toast"
          color={entry.type === "error" ? "red" : "green"}
          withCloseButton
          onClose={() => setEntry(null)}
        >
          {entry.message}
        </Alert>
      )}
      <Modal
        opened={opened}
        onClose={() => setOpened(false)}
        title="Histórico de notificações"
        size="lg"
      >
        <Stack>
          {!history.length && (
            <Text c="dimmed">
              Nenhuma notificação nesta instalação do navegador.
            </Text>
          )}
          {[...history].reverse().map((item) => (
            <Alert
              key={item.id}
              color={item.type === "error" ? "red" : "green"}
              title={new Date(item.time).toLocaleString()}
              onClick={safe(() => copy(item.message))}
            >
              <Text style={{ whiteSpace: "pre-wrap" }}>{item.message}</Text>
            </Alert>
          ))}
        </Stack>
      </Modal>
    </>
  );
}

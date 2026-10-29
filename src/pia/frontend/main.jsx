import React, { useState, useEffect } from "react";
import { createRoot } from "react-dom/client";
import {
  MantineProvider,
  createTheme,
  Button,
  Textarea,
  Group,
  Text,
  Stack,
  Loader,
} from "@mantine/core";
import "@mantine/core/styles.css";
import "./workspace.css";
import Workspace from "./Workspace";
import CaptureEditor from "../../../Plugins/Apps/screenshots/web/CaptureEditor.jsx";
import { api, session, watchJob, report, safe } from "./api";
import { ErrorAlert } from "./shared";
const theme = createTheme({
  primaryColor: "violet",
  defaultRadius: "md",
  fontFamily: "Inter, Segoe UI, sans-serif",
  colors: {
    dark: [
      "#eeeeF5",
      "#c8c4d4",
      "#a09aac",
      "#827c93",
      "#494251",
      "#34303e",
      "#24212c",
      "#19171f",
      "#131218",
      "#0e0d13",
    ],
  },
  components: {
    Button: { defaultProps: { variant: "filled" } },
    Paper: { defaultProps: { radius: "lg" } },
    Tooltip: { defaultProps: { withinPortal: true } },
  },
});
class Boundary extends React.Component {
  state = { error: null };
  static getDerivedStateFromError(error) {
    return { error };
  }
  componentDidCatch(error) {
    report(error);
  }
  render() {
    return this.state.error ? (
      <div style={{ padding: 30 }}>
        <Text c="red">{this.state.error.message}</Text>
        <Button onClick={() => location.reload()}>Recarregar</Button>
      </div>
    ) : (
      this.props.children
    );
  }
}
function MiniComposer() {
  const [text, setText] = useState(""),
    [chat, setChat] = useState(null),
    [busy, setBusy] = useState(false);
  useEffect(() => {
    session()
      .then(() => api("/chat/messages?chat=_mini"))
      .then((value) => setText(value.draft || ""))
      .catch(report);
  }, []);
  return (
    <Stack p="md">
      <ErrorAlert />
      <Textarea
        aria-label="Mensagem"
        placeholder="Mensagem para a PIA…"
        autosize
        minRows={2}
        maxRows={5}
        value={text}
        onChange={(event) => {
          setText(event.target.value);
          api("/chat/draft", { chat: "_mini", text: event.target.value }).catch(
            report,
          );
        }}
        onKeyDown={(event) => {
          if (
            event.key === "Enter" &&
            !event.shiftKey &&
            !event.nativeEvent.isComposing
          ) {
            event.preventDefault();
            document.querySelector("#mini-send")?.click();
          }
        }}
      />
      <Group justify="space-between">
        <Button
          variant="subtle"
          size="xs"
          onClick={safe(() => api("/native", { action: "mini-compose-close" }))}
        >
          Fechar
        </Button>
        <Text size="xs" c="dimmed">
          Enter envia · Shift+Enter quebra a linha
        </Text>
        <Button
          id="mini-send"
          disabled={busy || !text.trim()}
          onClick={safe(async () => {
            setBusy(true);
            try {
              const id = chat || (await api("/chat/new", {})).id;
              setChat(id);
              const result = await api("/chat/send", {
                chat: id,
                text,
                request: crypto.randomUUID(),
              });
              setText("");
              await api("/chat/draft", { chat: "_mini", text: "" });
              await api("/native", {
                action: "mini-job",
                payload: { job: result.job },
              });
              await api("/native", { action: "mini-compose-close" });
            } finally {
              setBusy(false);
            }
          })}
        >
          Enviar
        </Button>
      </Group>
    </Stack>
  );
}
let standalone = null;
const match = location.pathname.match(
  /^\/apps\/(podcast_automation|screenshots|object_storage|music)\//,
);
if (match)
  standalone = {
    view: "app",
    app: match[1],
    sub: location.pathname.endsWith("about.html") ? "about" : "principal",
  };
const connector = location.pathname.match(
  /^\/connectors\/(discord|object_storage)\/web\//,
);
if (connector) standalone = { view: "connectors", connector: connector[1] };
createRoot(document.getElementById("root")).render(
  <MantineProvider theme={theme} forceColorScheme="dark">
    <Boundary>
      {location.pathname.endsWith("/screenshots/capture.html") ? (
        <>
          <ErrorAlert />
          <CaptureEditor />
        </>
      ) : location.pathname.startsWith("/mini/") ? (
        <MiniComposer />
      ) : (
        <Workspace standalone={standalone} />
      )}
    </Boundary>
  </MantineProvider>,
);

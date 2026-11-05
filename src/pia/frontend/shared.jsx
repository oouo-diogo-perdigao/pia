import { formatTime } from "./forms";
import React, {
  useState,
  useRef,
  useEffect,
  useLayoutEffect,
  createContext,
  useContext,
} from "react";
import {
  ActionIcon,
  Tooltip,
  Progress,
  Group,
  Text,
  Paper,
  Button,
  Alert,
  TextInput,
  Collapse,
} from "@mantine/core";
import {
  Check,
  Trash2,
  Copy,
  ArrowDown,
  ExternalLink,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import { safe, report, copy } from "./api";
export const Context = createContext({});
export const usePia = () => useContext(Context);
export function Icon({
  icon: Glyph,
  label,
  onClick,
  danger = false,
  confirm = false,
  feedback = false,
  ...props
}) {
  const [armed, setArmed] = useState(false),
    [ok, setOk] = useState(false);
  const timer = useRef();
  useEffect(() => () => clearTimeout(timer.current), []);
  return (
    <Tooltip
      label={armed ? "Clique novamente para excluir" : label}
      openDelay={250}
    >
      <ActionIcon
        aria-label={label}
        variant={armed ? "filled" : "subtle"}
        color={danger || armed ? "red" : "gray"}
        onClick={safe(async (event) => {
          if (confirm && !armed) {
            setArmed(true);
            timer.current = setTimeout(() => setArmed(false), 5000);
            return;
          }
          await onClick?.(event);
          if (feedback && !confirm) {
            clearTimeout(timer.current);
            setOk(true);
            timer.current = setTimeout(() => setOk(false), 2000);
          }
          setArmed(false);
        })}
        {...props}
      >
        {ok ? <Check size={17} /> : <Glyph size={18} />}
      </ActionIcon>
    </Tooltip>
  );
}
export function Nav({ children, active, onClick, ...props }) {
  return (
    <Button
      className={"nav-button" + (active ? " active" : "")}
      variant="subtle"
      justify="flex-start"
      fullWidth
      onClick={onClick}
      {...props}
    >
      {children}
    </Button>
  );
}
export function WorkProgress({ value }) {
  if (!value) return null;
  const percent = Math.max(0, Math.min(100, Number(value.percent) || 0));
  return (
    <Paper withBorder p="md" className="work-progress">
      <Group justify="space-between">
        <Text size="sm">
          {value.label || value.state || "Processando"}
          {value.processed != null && value.duration > 0
            ? " · " +
              formatTime(value.processed) +
              " / " +
              formatTime(value.duration)
            : ""}
        </Text>
        <Text size="sm">
          {value.speed > 0 ? `Speed ${Number(value.speed).toFixed(1)}× · ` : ""}
          {value.total ? `${value.completed || 0}/${value.total} · ` : ""}
          {percent.toFixed(1)}%
        </Text>
      </Group>
      <Progress
        value={percent}
        animated={!["completed", "error"].includes(value.state)}
        color={value.state === "error" ? "red" : "violet"}
        size="sm"
        mt="xs"
      />
    </Paper>
  );
}
export function LogViewer({
  text = "",
  onClear,
  onOpen,
  title = "Log",
  height = 300,
}) {
  const [collapsed, setCollapsed] = useState(false),
    [query, setQuery] = useState("");
  const ref = useRef(),
    follow = useRef(true),
    [following, setFollowing] = useState(true);
  useLayoutEffect(() => {
    if (!text) {
      follow.current = true;
      setFollowing(true);
    }
    if (follow.current && ref.current)
      ref.current.scrollTop = ref.current.scrollHeight;
  }, [text]);
  return (
    <Paper withBorder p="md" className="log-panel">
      <Group justify="space-between">
        <Group gap={4}>
          <Icon
            icon={collapsed ? ChevronRight : ChevronDown}
            label={collapsed ? "Expandir log" : "Minimizar log"}
            onClick={() => setCollapsed((value) => !value)}
          />
          <Text fw={600}>{title}</Text>
        </Group>
        <Group gap={4}>
          {!following && (
            <Icon
              icon={ArrowDown}
              label="Voltar ao fim e acompanhar"
              onClick={() => {
                follow.current = true;
                setFollowing(true);
                ref.current.scrollTop = ref.current.scrollHeight;
              }}
            />
          )}
          <Icon
            icon={ExternalLink}
            label="Abrir log"
            onClick={
              onOpen ||
              (() => {
                const url = URL.createObjectURL(
                  new Blob([text], { type: "text/plain;charset=utf-8" }),
                );
                window.open(url, "_blank", "noopener");
                setTimeout(() => URL.revokeObjectURL(url), 60000);
              })
            }
          />
          {onClear && (
            <Icon icon={Trash2} label="Limpar log" onClick={onClear} />
          )}
        </Group>
      </Group>
      <Collapse in={!collapsed}>
        <TextInput
          size="xs"
          mt="xs"
          placeholder="Buscar no log"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        <pre
          ref={ref}
          className="log-viewer"
          style={{ height }}
          onScroll={() => {
            const node = ref.current;
            follow.current =
              node.scrollHeight - node.scrollTop - node.clientHeight < 24;
            setFollowing(follow.current);
          }}
        >
          {query
            ? text
                .split("\n")
                .filter((line) =>
                  line.toLowerCase().includes(query.toLowerCase()),
                )
                .join("\n")
            : text}
        </pre>
      </Collapse>
    </Paper>
  );
}
export function ErrorAlert() {
  const [error, setError] = useState(""),
    timer = useRef(),
    remaining = useRef(20000),
    started = useRef(0),
    hovered = useRef(false);
  const start = () => {
    started.current = Date.now();
    timer.current = setTimeout(() => setError(""), remaining.current);
  };
  useEffect(() => {
    const listener = (event) => {
      clearTimeout(timer.current);
      remaining.current = 20000;
      setError(String(event.detail));
      if (!hovered.current) start();
    };
    const rejection = (event) => {
      event.preventDefault();
      report(event.reason);
    };
    window.addEventListener("pia:error", listener);
    window.addEventListener("unhandledrejection", rejection);
    return () => {
      window.removeEventListener("pia:error", listener);
      window.removeEventListener("unhandledrejection", rejection);
      clearTimeout(timer.current);
    };
  }, []);
  return (
    error && (
      <Alert
        color="red"
        className="error-toast"
        title="Erro · clique para copiar"
        withCloseButton
        onClose={() => setError("")}
        onClick={() => safe(() => copy(error))()}
        onMouseEnter={() => {
          hovered.current = true;
          clearTimeout(timer.current);
          remaining.current = Math.max(
            0,
            remaining.current - (Date.now() - started.current),
          );
        }}
        onMouseLeave={() => {
          hovered.current = false;
          start();
        }}
      >
        <pre>{error}</pre>
      </Alert>
    )
  );
}
export function About({ children }) {
  return (
    <Paper withBorder p="xl">
      <Text size="lg" fw={600} mb="md">
        Como usar
      </Text>
      {children}
    </Paper>
  );
}

import React, { useState, useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { Paper, Button, Text } from "@mantine/core";
import { BellOff, Volume2, VolumeX, Bell } from "lucide-react";
import { api, safe } from "./api";
import { usePia } from "./shared";

export function CountBadge({ count }) {
  return count > 0 ? (
    <span className="notification-count" aria-label={count + " não lidas"}>
      {count > 99 ? "99+" : count}
    </span>
  ) : null;
}

export default function NotificationMenu({ source, children, className = "" }) {
  const { state, refresh } = usePia();
  const [menu, setMenu] = useState(null);
  const panel = useRef();
  const settings = state.notifications?.settings || {
    read_aloud: false,
    muted: [],
  };
  const enabled = source
    ? settings.muted.includes(source)
    : settings.read_aloud;
  useEffect(() => {
    const close = (event) => {
      if (!panel.current?.contains(event.target)) setMenu(null);
    };
    const escape = (event) => {
      if (event.key === "Escape") setMenu(null);
    };
    const other = () => setMenu(null);
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", escape);
    document.addEventListener("pia:context-open", other);
    return () => {
      document.removeEventListener("pointerdown", close);
      document.removeEventListener("keydown", escape);
      document.removeEventListener("pia:context-open", other);
    };
  }, []);
  const open = (event) => {
    event.preventDefault();
    event.stopPropagation();
    document.dispatchEvent(new Event("pia:context-open"));
    setMenu({
      x: Math.max(4, Math.min(event.clientX, innerWidth - 290)),
      y: Math.max(4, Math.min(event.clientY, innerHeight - 105)),
    });
  };
  async function toggle() {
    await api(
      "/notifications/settings",
      source
        ? {
            ...settings,
            muted: enabled
              ? settings.muted.filter((item) => item !== source)
              : [...settings.muted, source],
          }
        : { ...settings, read_aloud: !enabled },
    );
    setMenu(null);
    await refresh();
  }
  const Glyph = source
    ? enabled
      ? Bell
      : BellOff
    : enabled
      ? VolumeX
      : Volume2;
  return (
    <div
      className={"notification-target " + className}
      onContextMenu={open}
      onKeyDown={(event) => {
        if (
          event.key === "ContextMenu" ||
          (event.shiftKey && event.key === "F10")
        ) {
          const box = event.currentTarget.getBoundingClientRect();
          open({
            preventDefault: () => event.preventDefault(),
            stopPropagation: () => event.stopPropagation(),
            clientX: box.right,
            clientY: box.bottom,
          });
        }
      }}
    >
      {children}
      {menu &&
        createPortal(
          <Paper
            ref={panel}
            role="menu"
            shadow="xl"
            withBorder
            p="xs"
            className="notification-menu"
            style={{
              position: "fixed",
              left: menu.x,
              top: menu.y,
              zIndex: 1500,
            }}
          >
            <Text size="xs" c="dimmed" px="xs">
              {source || "Notificações"}
            </Text>
            <Button
              role="menuitemcheckbox"
              aria-checked={enabled}
              variant="subtle"
              leftSection={<Glyph size={16} />}
              onClick={safe(toggle)}
            >
              {source
                ? enabled
                  ? "Ativar notificações"
                  : "Silenciar notificações"
                : enabled
                  ? "Desativar leitura automática"
                  : "Ler notificações automaticamente"}
            </Button>
          </Paper>,
          document.body,
        )}
    </div>
  );
}

import React, { useState, useEffect } from "react";
import { Paper, Group, Text, Slider } from "@mantine/core";
import { Play, Pause, X } from "lucide-react";
import { Icon } from "./shared";
import { formatTime } from "./forms";
// Loaded as one browser module, shared with app HTML using the SDK.
import {
  playMedia,
  pauseMedia,
  stopMedia,
  seekMedia,
  subscribeMedia,
  mediaSnapshot,
} from "/pia/media.js";
export { playMedia };
export function MediaTrack({ url, title = "Música" }) {
  return (
    <Group gap="xs">
      <Icon
        icon={Play}
        label={"Tocar " + title}
        onClick={() => playMedia(url, title)}
      />
      <Text size="sm">{title}</Text>
    </Group>
  );
}
export default function MediaPlayer() {
  const [state, setState] = useState(mediaSnapshot);
  useEffect(() => subscribeMedia(setState), []);
  if (!state.url) return null;
  return (
    <Paper className="media-dock" withBorder shadow="lg" p="sm">
      <Group wrap="nowrap">
        <Icon
          icon={state.playing ? Pause : Play}
          label={state.playing ? "Pausar" : "Tocar"}
          onClick={() =>
            state.playing ? pauseMedia() : playMedia(state.url, state.title)
          }
        />
        <div className="grow">
          <Text size="sm" lineClamp={1}>
            {state.title}
          </Text>
          <Slider
            aria-label="Posição da música"
            value={state.current}
            max={state.duration || 1}
            onChange={seekMedia}
          />
        </div>
        <Text size="xs">
          {formatTime(state.current)} / {formatTime(state.duration)}
        </Text>
        <Icon icon={X} label="Encerrar reprodução" onClick={stopMedia} />
      </Group>
    </Paper>
  );
}

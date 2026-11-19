import { Button } from "@mantine/core";
import { ArrowUpRight } from "lucide-react";
import React from "react";
import { safe } from "../../api/client";

export default function SuggestionChips({
  suggestions,
  busy,
  label = "Sugestões rápidas",
  onSendSuggestion,
}) {
  if (!Array.isArray(suggestions) || suggestions.length === 0) return null;
  return (
    <div className="chat-suggestions" role="group" aria-label={label}>
      {suggestions.map((item) => (
        <Button
          key={item.prompt}
          size="xs"
          variant="light"
          color="violet"
          radius="xl"
          className="chat-suggestion-btn"
          disabled={busy}
          title={item.prompt}
          rightSection={<ArrowUpRight size={13} />}
          onClick={safe(() => onSendSuggestion?.(item.prompt))}
        >
          {item.label}
        </Button>
      ))}
    </div>
  );
}

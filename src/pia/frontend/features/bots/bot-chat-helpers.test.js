import { describe, it } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  buildBotChatPayload,
  findBotChatRecord,
  getBotSuggestions,
  mergeStreamingMessages,
} from "./bot-chat-helpers.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.resolve(here, "../..");
const pluginsRoot = path.resolve(frontendRoot, "../../../Plugins");

function collectJsxFiles(dir, out = []) {
  if (!fs.existsSync(dir)) return out;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.name === "node_modules" || entry.name === "dist") continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) collectJsxFiles(full, out);
    else if (entry.isFile() && entry.name.endsWith(".jsx")) out.push(full);
  }
  return out;
}

describe("features/bots/bot-chat-helpers & JSX import integrity", () => {
  it("builds valid /chat/send payloads with bot_id and optional chat/system_prompt", () => {
    const payload = buildBotChatPayload({
      botId: "secretaria",
      text: "  Quais meus compromissos de hoje?  ",
      request: "req-1",
    });
    assert.deepEqual(payload, {
      bot_id: "secretaria",
      text: "Quais meus compromissos de hoje?",
      request: "req-1",
    });

    const withChat = buildBotChatPayload({
      botId: "bot-123",
      text: "Resumir tarefas",
      chatId: "chat-abc",
      systemPrompt: "Seja direto.",
    });
    assert.deepEqual(withChat, {
      bot_id: "bot-123",
      text: "Resumir tarefas",
      chat: "chat-abc",
      system_prompt: "Seja direto.",
    });

    assert.throws(() =>
      buildBotChatPayload({ botId: "secretaria", text: "   " }),
    );
  });

  it("finds existing persistent bot chat by stored ID or Bot title", () => {
    const chats = [
      { id: "c1", title: "Nova conversa" },
      { id: "c2", title: "Bot · secretaria" },
    ];
    assert.equal(findBotChatRecord(chats, "secretaria")?.id, "c2");
    assert.equal(findBotChatRecord(chats, "secretaria", "c1")?.id, "c1");
    assert.equal(findBotChatRecord(chats, "outro"), null);
  });

  it("returns tailored suggestions and updates streaming assistant messages", () => {
    assert.ok(
      getBotSuggestions("secretaria").some((s) => s.includes("compromissos")),
    );
    assert.ok(getBotSuggestions("custom-bot").length >= 2);

    const updated = mergeStreamingMessages(
      [
        { id: "u1", role: "user", text: "Oi" },
        { id: "a1", role: "assistant", text: "", status: "running" },
      ],
      "a1",
      { text: "Olá!", status: "done" },
    );
    assert.equal(updated[1].text, "Olá!");
    assert.equal(updated[1].status, "done");
  });

  it("has zero missing PascalCase JSX component imports across frontend and Plugins", () => {
    const jsxFiles = [
      ...collectJsxFiles(frontendRoot),
      ...collectJsxFiles(pluginsRoot),
    ];
    assert.ok(jsxFiles.length > 0);
    const errors = [];
    for (const filePath of jsxFiles) {
      const src = fs
        .readFileSync(filePath, "utf8")
        .replace(/\/\*[\s\S]*?\*\//g, "")
        .replace(/^\s*\/\/.*$/gm, "");
      const defined = new Set();
      for (const m of src.matchAll(/import\s+([\s\S]*?)\s+from\s+["']/g)) {
        const clean = m[1].replace(/[{}*,\s]+/g, " ").replace(/\bas\b/g, " ");
        for (const w of clean.split(/\s+/)) {
          if (/^[A-Z][A-Za-z0-9_]*$/.test(w)) defined.add(w);
        }
      }
      for (const m of src.matchAll(
        /\b(?:function|class|const|let|var)\s+([A-Z][A-Za-z0-9_]*)\b/g,
      )) {
        defined.add(m[1]);
      }
      for (const m of src.matchAll(/:\s*([A-Z][A-Za-z0-9_]*)\b/g)) {
        defined.add(m[1]);
      }
      for (const m of src.matchAll(/<([A-Z][A-Za-z0-9_]*)(?=[\s/>])/g)) {
        if (!defined.has(m[1])) {
          errors.push(`${path.relative(frontendRoot, filePath)} -> <${m[1]}>`);
        }
      }
    }
    assert.deepEqual(errors, []);
  });
});

export const SECRETARIA_SUGGESTIONS = [
  "Quais são meus compromissos de hoje?",
  "Tenho e-mails importantes recentes?",
  "Resuma o que está pendente para esta semana",
];

export const DEFAULT_BOT_SUGGESTIONS = [
  "Olá! Como você pode me ajudar hoje?",
  "Quais tarefas você consegue executar?",
  "Faça um resumo rápido das suas instruções",
];

export function getBotSuggestions(botId) {
  const id = String(botId || "")
    .trim()
    .toLowerCase();
  if (id === "secretaria" || id === "native:secretaria") {
    return SECRETARIA_SUGGESTIONS;
  }
  return DEFAULT_BOT_SUGGESTIONS;
}

export function buildBotChatPayload({
  botId,
  text,
  chatId = "",
  systemPrompt = "",
  request = "",
}) {
  const cleanText = String(text || "").trim();
  if (!cleanText) {
    throw new Error("Digite uma mensagem para enviar ao bot.");
  }
  const cleanBotId = String(botId || "").trim();
  if (!cleanBotId) {
    throw new Error("Selecione um bot para conversar.");
  }
  const payload = {
    bot_id: cleanBotId,
    text: cleanText,
  };
  if (request) payload.request = String(request);
  if (chatId) payload.chat = String(chatId);
  if (systemPrompt && String(systemPrompt).trim()) {
    payload.system_prompt = String(systemPrompt).trim();
  }
  return payload;
}

export function findBotChatRecord(chats, botId, storedChatId = "") {
  const list = Array.isArray(chats) ? chats : [];
  if (storedChatId) {
    const byId = list.find((c) => c?.id === storedChatId);
    if (byId) return byId;
  }
  const expectedTitle = `Bot · ${String(botId || "").trim()}`;
  return list.find((c) => c?.title === expectedTitle) || null;
}

export function mergeStreamingMessages(prevMessages, assistantMsgId, patch) {
  return (Array.isArray(prevMessages) ? prevMessages : []).map((msg) =>
    msg.id === assistantMsgId ? { ...msg, ...patch } : msg,
  );
}

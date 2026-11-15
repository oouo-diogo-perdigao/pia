import test from "node:test";
import assert from "node:assert/strict";
import {
  CHAT_AUTO_MODEL_SENTINEL,
  buildChatModelOptions,
  buildChatSendPayload,
  buildChatActionPayload,
  formatMessageInfo,
  extractMessageMedia,
  extractMessageSuggestions,
  prepareSpeechText,
  createChatSpeechController,
} from "./chat-helpers.js";

test("buildChatModelOptions combines auto option with /chat/models response and deduplicates", () => {
  const { options, defaultModel, hasCatalog } = buildChatModelOptions({
    default: "free",
    selected: "auto",
    models: [
      {
        id: "auto",
        label: "Automático (padrão PIA)",
        provider: "auto",
        model: "free",
        tier: "auto",
        available: true,
      },
      {
        id: "gemini/gemini-2.5-flash",
        label: "gemini: gemini-2.5-flash",
        provider: "gemini",
        model: "gemini-2.5-flash",
        tier: "free",
        available: true,
      },
      "gemini/gemini-2.5-flash",
      {
        id: "groq/llama-3.3-70b",
        provider: "groq",
        model: "llama-3.3-70b",
        tier: "free",
      },
      {
        id: "openai/gpt-5",
        provider: "openai",
        model: "gpt-5",
        tier: "paid",
        available: false,
      },
    ],
  });

  assert.equal(hasCatalog, true);
  assert.equal(defaultModel, "free");
  assert.equal(options[0].value, CHAT_AUTO_MODEL_SENTINEL);
  assert.equal(options[0].label, "Automático (Padrão)");
  assert.equal(options.length, 4);
  assert.equal(options[1].value, "gemini/gemini-2.5-flash");
  assert.equal(options[1].label, "gemini: gemini-2.5-flash (free)");
  assert.equal(options[2].value, "groq/llama-3.3-70b");
  assert.equal(options[2].label, "llama-3.3-70b (Groq · free)");
  assert.equal(options[3].disabled, true);
});

test("buildChatModelOptions falls back to /settings when /chat/models is unavailable", () => {
  const { options, hasCatalog } = buildChatModelOptions(null, {
    LLM_MODEL: "gemini/gemini-3-flash-preview",
    LLM_GEMINI_FREE_MODELS: "gemini-2.5-flash, gemini-3-flash-preview",
    LLM_GROQ_FREE_MODELS: "llama-3.3-70b",
    LLM_LOCAL_MODEL: "llama3.2",
  });

  assert.equal(hasCatalog, false);
  const values = options.map((o) => o.value);
  assert.deepEqual(values, [
    CHAT_AUTO_MODEL_SENTINEL,
    "gemini/gemini-3-flash-preview",
    "gemini/gemini-2.5-flash",
    "groq/llama-3.3-70b",
    "llama3.2",
  ]);
});

test("buildChatSendPayload and buildChatActionPayload include model only when non-auto", () => {
  assert.deepEqual(
    buildChatSendPayload({
      chat: "c1",
      text: "Oi",
      request: "r1",
      model: CHAT_AUTO_MODEL_SENTINEL,
    }),
    { chat: "c1", text: "Oi", request: "r1" },
  );

  assert.deepEqual(
    buildChatSendPayload({
      chat: "c1",
      text: "Oi",
      request: "r1",
      model: "gemini/gemini-2.5-flash",
    }),
    {
      chat: "c1",
      text: "Oi",
      request: "r1",
      model: "gemini/gemini-2.5-flash",
    },
  );

  assert.deepEqual(
    buildChatActionPayload({
      chat: "c1",
      id: 42,
      action: "retry",
      model: "groq/llama-3.3-70b",
    }),
    {
      chat: "c1",
      id: 42,
      action: "retry",
      model: "groq/llama-3.3-70b",
    },
  );
});

test("formatMessageInfo extracts model, provider, and tools_used cleanly", () => {
  const info = formatMessageInfo({
    role: "assistant",
    model: "gemini/gemini-2.5-flash",
    tools_used: [
      "mcp_screenshots_capture",
      { name: "suno_music", status: "ok" },
    ],
  });

  assert.equal(info.hasMetadata, true);
  assert.equal(info.provider, "gemini");
  assert.equal(info.shortModel, "gemini-2.5-flash");
  assert.equal(info.modelDisplay, "gemini-2.5-flash (Gemini)");
  assert.deepEqual(info.tools, [
    { name: "mcp_screenshots_capture", detail: "" },
    { name: "suno_music", detail: "ok" },
  ]);

  const mcpTagged = formatMessageInfo({
    role: "assistant",
    content: "Concluído",
    meta: {
      mcp_server: "Suno",
      account_mode: "distributed",
      mcp_account: "Conta 2",
    },
  });
  assert.equal(mcpTagged.hasMetadata, true);
  assert.equal(mcpTagged.accountMode, "distributed");
  assert.equal(mcpTagged.accountModeLabel, "Distribuído");
  assert.equal(mcpTagged.mcpBadge, "MCP • Suno · Distribuído · Conta 2");

  const legacy = formatMessageInfo({ role: "assistant", content: "Oi" });
  assert.equal(legacy.hasMetadata, false);
  assert.equal(legacy.modelDisplay, "");
  assert.equal(legacy.mcpBadge, "");
  assert.deepEqual(legacy.tools, []);
});

test("extractMessageMedia separates MCP screenshots, music audio, and bucket/transcript files without duplicating Markdown links", () => {
  const media = extractMessageMedia({
    content: "Aqui está ![captura](/api/pia/chat/assets/already.png)",
    attachments: [
      { type: "image", url: "/api/pia/chat/assets/already.png", title: "Dup" },
      {
        type: "screenshot",
        url: "/api/pia/chat/assets/newshot.png",
        title: "Tela",
      },
      { type: "audio", url: "/api/pia/music/files/song.mp3", title: "Trilha" },
      {
        type: "bucket",
        name: "sessao-rpg.txt",
        bucket: "campanha",
        url: "/api/pia/apps/object_storage/download?key=sessao-rpg.txt",
        transcript: "Turno 1: o grupo entra na taverna.",
      },
    ],
  });

  assert.deepEqual(media.images, [
    {
      url: "/api/pia/chat/assets/newshot.png",
      title: "Tela",
      downloadUrl: "/api/pia/chat/assets/newshot.png",
    },
  ]);
  assert.deepEqual(media.audios, [
    {
      url: "/api/pia/music/files/song.mp3",
      title: "Trilha",
      downloadUrl: "/api/pia/music/files/song.mp3",
    },
  ]);
  assert.deepEqual(media.files, [
    {
      url: "/api/pia/apps/object_storage/download?key=sessao-rpg.txt",
      name: "sessao-rpg.txt",
      kind: "bucket",
      bucket: "campanha",
      transcript: "Turno 1: o grupo entra na taverna.",
    },
  ]);
});

test("prepareSpeechText removes markdown formatting", () => {
  assert.equal(
    prepareSpeechText(
      "## Olá **mundo**!\nVeja [o link](https://x.com)\n```js\ncode\n```",
    ),
    "Olá mundo ! Veja o link",
  );
});

test("createChatSpeechController switches Sound -> Stop immediately, stops Audio + SSE + remote job on Stop, and restores on onended", async () => {
  const states = [];
  const cancelledJobs = [];
  let closedSources = 0;
  let fakeAudio = null;

  const controller = createChatSpeechController({
    synthesize: async () => ({ jobId: "tts-job-1" }),
    watch: (_jobId, cb) => {
      setTimeout(
        () =>
          cb({
            type: "done",
            result: { audio_url: "/api/pia/tts/previews/tts-job-1/audio" },
          }),
        10,
      );
      return {
        close() {
          closedSources += 1;
        },
      };
    },
    cancelRemote: async (entry) => {
      cancelledJobs.push({
        jobId: entry.remoteJobId,
        started: entry.playbackStarted,
      });
    },
    createAudio: (url) => {
      fakeAudio = {
        url,
        currentTime: 5,
        paused: false,
        onended: null,
        onerror: null,
        pause() {
          this.paused = true;
        },
        play() {
          return Promise.resolve();
        },
      };
      return fakeAudio;
    },
    onStateChange: (s) => states.push(s),
  });

  // Start speaking message 10: transitions to loading immediately, then playing
  const promise = controller.toggle({ id: 10, content: "Olá **PIA**" });
  assert.deepEqual(states[0], { activeId: 10, status: "loading" });

  await new Promise((r) => setTimeout(r, 30));
  assert.deepEqual(states[1], { activeId: 10, status: "playing" });
  assert.equal(fakeAudio.url, "/api/pia/tts/previews/tts-job-1/audio");

  // Natural audio finish restores Sound icon
  fakeAudio.onended();
  const played = await promise;
  assert.equal(played, true);
  assert.deepEqual(states.at(-1), { activeId: null, status: "idle" });
  assert.equal(fakeAudio.paused, true);
  assert.equal(fakeAudio.currentTime, 0);
  assert.equal(closedSources, 1);
  assert.equal(cancelledJobs.length, 0);

  // Clicking Stop while synthesizing cancels remote job + closes watcher + restores icon
  const pendingStates = [];
  let sourceClosedDuringStop = 0;
  const controller2 = createChatSpeechController({
    synthesize: async () => ({ jobId: "tts-job-2" }),
    watch: () => ({
      close() {
        sourceClosedDuringStop += 1;
      },
    }),
    cancelRemote: async (entry) => {
      cancelledJobs.push({
        jobId: entry.remoteJobId,
        started: entry.playbackStarted,
      });
    },
    onStateChange: (s) => pendingStates.push(s),
  });

  const p2 = controller2.toggle({ id: 20, content: "Texto longo" });
  await new Promise((r) => setTimeout(r, 5));
  assert.deepEqual(pendingStates[0], { activeId: 20, status: "loading" });

  // Second toggle on same message stops it immediately
  await controller2.toggle({ id: 20, content: "Texto longo" });
  assert.equal(await p2, false);
  assert.equal(sourceClosedDuringStop, 1);
  assert.deepEqual(cancelledJobs, [{ jobId: "tts-job-2", started: false }]);
  assert.deepEqual(pendingStates.at(-1), { activeId: null, status: "idle" });
});

test("extractMessageSuggestions reads structured meta.suggestions and ignores user/pending messages", () => {
  assert.deepEqual(
    extractMessageSuggestions({
      role: "user",
      content: "Sugestões:\n- Fazer algo",
    }),
    [],
  );

  assert.deepEqual(
    extractMessageSuggestions({
      id: 1,
      role: "assistant",
      content: "Tudo pronto!",
      meta: {
        suggestions: [
          "Ver resumo",
          { label: "Rodar testes", prompt: "Execute todos os testes" },
          "ver resumo",
        ],
      },
    }),
    [
      { label: "Ver resumo", prompt: "Ver resumo" },
      { label: "Rodar testes", prompt: "Execute todos os testes" },
    ],
  );
});

test("extractMessageSuggestions extracts trailing Markdown suggestion lists and quoted prompts while ignoring code blocks and factual lists", () => {
  const fromHeader = extractMessageSuggestions({
    id: 2,
    role: "assistant",
    content: [
      "Aqui está a análise completa do servidor.",
      "",
      "```bash",
      "# Sugestões:",
      "# - rm -rf /tmp/fake",
      "```",
      "",
      "### Próximos passos",
      '- Pedir detalhes: "Me explique a arquitetura da PIA"',
      "- **Listar buckets ativos** — consulta seus buckets configurados",
      "- Opção 3: Reiniciar serviço da porta 8762",
    ].join("\n"),
  });

  assert.deepEqual(fromHeader, [
    {
      label: "Me explique a arquitetura da PIA",
      prompt: "Me explique a arquitetura da PIA",
    },
    { label: "Listar buckets ativos", prompt: "Listar buckets ativos" },
    {
      label: "Reiniciar serviço da porta 8762",
      prompt: "Reiniciar serviço da porta 8762",
    },
  ]);

  const fromQuestion = extractMessageSuggestions({
    id: 3,
    role: "assistant",
    content:
      "Encontrei 3 arquivos na campanha. Como gostaria de prosseguir?\n1. Resumir última sessão\n2. Comparar personagens",
  });
  assert.deepEqual(fromQuestion, [
    { label: "Resumir última sessão", prompt: "Resumir última sessão" },
    { label: "Comparar personagens", prompt: "Comparar personagens" },
  ]);

  const factualListOnly = extractMessageSuggestions({
    id: 4,
    role: "assistant",
    content:
      "Os 3 estados da água são:\n- Sólido\n- Líquido\n- Gasoso\n\nEspero que tenha ajudado.",
  });
  assert.deepEqual(factualListOnly, []);
});

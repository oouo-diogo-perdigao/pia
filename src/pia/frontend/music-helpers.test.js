import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  MUSIC_PROVIDERS_UPDATED_EVENT,
  MUSIC_PROVIDER_LABELS,
  SUNO_CANCEL_WARNING,
  SUNO_DURATION_HINT,
  SUNO_HINT_TEXT,
  SUNO_REUSE_WARNING,
  SUNO_SETTINGS_ROUTE,
  buildGeneratorOptions,
  buildMusicSelectPayload,
  findSunoProvider,
  generatorHints,
  isGeneratorAvailable,
  notifyMusicProvidersUpdated,
  finalStateForError,
  interruptedProgressLabel,
  musicDraftSnapshot,
  partialBatchLabel,
  providerLabel,
  resolveInitialProvider,
  resolveProviderAfterRefresh,
  resolveReuseProvider,
  runWithMusicProvidersUpdate,
  selectionToMusicDraft,
  shouldShowSunoHint,
  shouldWarnSunoOpensInLocal,
  sunoSettingsRoute,
} from "./music-helpers.js";

describe("music-helpers T7: select sem campos manuais e evento", () => {
  async function withWindowEvents(run) {
    const events = [];
    const previous = globalThis.window;
    globalThis.window = {
      dispatchEvent(ev) {
        events.push(ev);
        return true;
      },
    };
    if (typeof globalThis.CustomEvent !== "function") {
      globalThis.CustomEvent = class CustomEvent {
        constructor(type) {
          this.type = type;
        }
      };
    }
    try {
      return await run(events);
    } finally {
      globalThis.window = previous;
    }
  }

  it("o usuário só vê 'Suno' (RN24)", () => {
    assert.equal(MUSIC_PROVIDER_LABELS.suno_mcp, "Suno");
  });

  it("draft e snapshot só com provider (RN06/RN22: sem URL, comando ou token)", () => {
    const draft = selectionToMusicDraft({
      provider: "suno_mcp",
      suno_mcp_url: "https://api.suno.com/mcp",
      suno_mcp_token_configured: true,
    });
    assert.deepEqual(draft, { provider: "suno_mcp" });
    assert.deepEqual(selectionToMusicDraft(null), { provider: "local" });
    assert.equal(
      musicDraftSnapshot(draft),
      JSON.stringify({ provider: "suno_mcp" }),
    );
  });

  it("/music/select recebe só provider e gemini_model, nunca suno_account_id", () => {
    assert.deepEqual(
      buildMusicSelectPayload({
        provider: "suno_mcp",
        suno_account_id: "a",
        suno_mcp_url: "x",
        suno_mcp_token: "segredo",
      }),
      { provider: "suno_mcp" },
    );
    assert.deepEqual(
      buildMusicSelectPayload({ provider: "gemini", gemini_model: " lyria " }),
      { provider: "gemini", gemini_model: "lyria" },
    );
    assert.deepEqual(buildMusicSelectPayload(), { provider: "local" });
  });

  it("findSunoProvider só reconhece o id suno_mcp", () => {
    assert.equal(
      findSunoProvider({
        providers: [{ id: "outra", url: "https://api.suno.com/mcp" }],
      }),
      null,
    );
    assert.equal(
      findSunoProvider({ providers: [{ id: "suno_mcp", available: true }] })
        .available,
      true,
    );
    assert.equal(findSunoProvider(null), null);
  });

  it("avisa RN04 quando Suno está salvo mas available não é true", () => {
    assert.equal(
      shouldWarnSunoOpensInLocal(
        { provider: "suno_mcp" },
        { id: "suno_mcp", available: false, reason: "pia_server_unsupported" },
      ),
      true,
    );
    assert.equal(
      shouldWarnSunoOpensInLocal(
        { provider: "suno_mcp" },
        { id: "suno_mcp", available: true },
      ),
      false,
    );
    assert.equal(
      shouldWarnSunoOpensInLocal({ provider: "local" }, {}, "local"),
      false,
    );
  });

  it("dispara pia:music-providers-updated no window", async () => {
    await withWindowEvents((events) => {
      notifyMusicProvidersUpdated();
      assert.equal(events.length, 1);
      assert.equal(events[0].type, MUSIC_PROVIDERS_UPDATED_EVENT);
    });
  });

  it("dispara o evento se a mutação ok e um passo posterior falha", async () => {
    await withWindowEvents(async (events) => {
      await assert.rejects(
        () =>
          runWithMusicProvidersUpdate(async (markMutated) => {
            markMutated();
            throw new Error("loadCatalog falhou");
          }),
        { message: "loadCatalog falhou" },
      );
      assert.equal(events.length, 1);
      assert.equal(events[0].type, MUSIC_PROVIDERS_UPDATED_EVENT);
    });
  });

  it("não dispara o evento se a ação falhar antes de mutar", async () => {
    await withWindowEvents(async (events) => {
      await assert.rejects(
        () =>
          runWithMusicProvidersUpdate(async () => {
            throw new Error("select falhou");
          }),
        { message: "select falhou" },
      );
      assert.equal(events.length, 0);
    });
  });
});

describe("music-helpers seletor dinâmico (Suno no app de Música)", () => {
  const catalog = (sunoAvailable, provider = "local") => ({
    providers: [
      { id: "local", label: "Local", available: true },
      { id: "gemini", label: "Gemini", available: false },
      {
        id: "suno_mcp",
        label: "Suno",
        kind: "mcp",
        available: sunoAvailable,
        endpoint_configured: true,
        credential_state: sunoAvailable ? "configured" : "missing",
        settings_route: { view: "settings", section: "Apps/music" },
      },
    ],
    selection: { provider },
  });
  const values = (options) => options.map((option) => option.value);

  it("mostra Suno quando o catálogo diz available=true (CA01)", () => {
    const options = buildGeneratorOptions(catalog(true));
    assert.deepEqual(values(options), ["local", "gemini", "suno_mcp", "flow"]);
    assert.equal(options.find((o) => o.value === "suno_mcp").label, "Suno");
    assert.equal(shouldShowSunoHint(catalog(true)), false);
  });

  it("esconde Suno e mostra a dica quando indisponível (CA02)", () => {
    assert.deepEqual(values(buildGeneratorOptions(catalog(false))), [
      "local",
      "gemini",
      "flow",
    ]);
    assert.equal(shouldShowSunoHint(catalog(false)), true);
    assert.equal(
      shouldShowSunoHint({ providers: [{ id: "local", available: true }] }),
      true,
    );
  });

  it("só aceita available === true (valores truthy não contam)", () => {
    const cat = catalog(true);
    cat.providers[2].available = "true";
    assert.ok(!values(buildGeneratorOptions(cat)).includes("suno_mcp"));
  });

  it("catálogo vazio ou com erro devolve local, gemini e flow sem dica", () => {
    for (const bad of [undefined, null, {}, { error: "boom" }, "x"]) {
      assert.deepEqual(values(buildGeneratorOptions(bad)), [
        "local",
        "gemini",
        "flow",
      ]);
      assert.equal(shouldShowSunoHint(bad), false);
      assert.equal(resolveInitialProvider(bad), "local");
    }
  });

  it("Suno salvo abre em suno_mcp se disponível, senão em local (CA03)", () => {
    assert.equal(resolveInitialProvider(catalog(true, "suno_mcp")), "suno_mcp");
    assert.equal(resolveInitialProvider(catalog(false, "suno_mcp")), "local");
    assert.equal(resolveInitialProvider(catalog(true, "gemini")), "gemini");
    assert.equal(
      resolveInitialProvider(catalog(true, "desconhecido")),
      "local",
    );
  });

  it("após recarregar o catálogo volta para local só se não estiver ocupado (CA04)", () => {
    assert.deepEqual(resolveProviderAfterRefresh("suno_mcp", catalog(true)), {
      provider: "suno_mcp",
      warning: null,
    });
    const fallback = resolveProviderAfterRefresh("suno_mcp", catalog(false));
    assert.equal(fallback.provider, "local");
    assert.match(fallback.warning, /Suno/);
    assert.deepEqual(
      resolveProviderAfterRefresh("suno_mcp", catalog(false), true),
      { provider: "suno_mcp", warning: null },
    );
    assert.deepEqual(resolveProviderAfterRefresh("flow", catalog(false)), {
      provider: "flow",
      warning: null,
    });
  });

  it("reutilizar faixa Suno: Suno se disponível, Local com aviso se não (CA08)", () => {
    const item = { provider: "suno_mcp", prompt: "lofi" };
    assert.deepEqual(resolveReuseProvider(item, catalog(true)), {
      provider: "suno_mcp",
      warning: null,
    });
    const reused = resolveReuseProvider(item, catalog(false));
    assert.equal(reused.provider, "local");
    assert.match(reused.warning, /Configurações → Música/);
  });

  it("reutilizar mantém local/gemini e manda desconhecido para local", () => {
    assert.deepEqual(resolveReuseProvider({ provider: "gemini" }, null), {
      provider: "gemini",
      warning: null,
    });
    assert.deepEqual(
      resolveReuseProvider({ provider: "flow" }, catalog(true)),
      {
        provider: "local",
        warning: null,
      },
    );
    assert.deepEqual(resolveReuseProvider({ provider: "xyz" }, catalog(true)), {
      provider: "local",
      warning: null,
    });
    assert.deepEqual(resolveReuseProvider(undefined, catalog(true)), {
      provider: "local",
      warning: null,
    });
  });

  it("rótulos curtos para o Histórico com fallback para o id", () => {
    assert.equal(providerLabel("suno_mcp"), "Suno");
    assert.equal(providerLabel("local"), "Local");
    assert.equal(providerLabel("gemini"), "Gemini");
    assert.equal(providerLabel("outro_provedor"), "outro_provedor");
    assert.equal(providerLabel(undefined), "");
    assert.equal(MUSIC_PROVIDER_LABELS.suno_mcp, "Suno");
  });

  it("rota do atalho vem do catálogo ou do padrão Apps/music", () => {
    assert.deepEqual(sunoSettingsRoute(catalog(false)), SUNO_SETTINGS_ROUTE);
    assert.deepEqual(sunoSettingsRoute(null), {
      view: "settings",
      section: "Apps/music",
    });
  });

  it("falha passageira do catálogo mantém o provedor atual sem aviso", () => {
    for (const bad of [undefined, null, {}, { error: "timeout" }]) {
      assert.deepEqual(resolveProviderAfterRefresh("suno_mcp", bad), {
        provider: "suno_mcp",
        warning: null,
      });
    }
  });

  it("resolveInitialProvider ignora flow salvo (não é gerador do backend)", () => {
    assert.equal(resolveInitialProvider(catalog(true, "flow")), "local");
  });

  it("isGeneratorAvailable direto", () => {
    assert.equal(isGeneratorAvailable("local", null), true);
    assert.equal(isGeneratorAvailable("gemini", catalog(false)), true);
    assert.equal(isGeneratorAvailable("flow", undefined), true);
    assert.equal(isGeneratorAvailable("suno_mcp", catalog(true)), true);
    assert.equal(isGeneratorAvailable("suno_mcp", catalog(false)), false);
    assert.equal(isGeneratorAvailable("suno_mcp", null), false);
    assert.equal(isGeneratorAvailable("xyz", catalog(true)), false);
    assert.equal(
      isGeneratorAvailable("suno_mcp", {
        providers: [
          {
            id: "outra-conta",
            url: "https://api.suno.com/mcp",
            available: true,
          },
        ],
      }),
      false, // T7: só o id suno_mcp (o MCP local/manual saiu, RN22)
    );
  });

  it("buildGeneratorOptions e sunoSettingsRoute devolvem cópias", () => {
    const first = buildGeneratorOptions(catalog(true));
    first[0].label = "alterado";
    first.push({ value: "x" });
    assert.equal(
      buildGeneratorOptions(catalog(true))[0].label,
      "Local · ACE-Step",
    );
    const cat = catalog(false);
    const route = sunoSettingsRoute(cat);
    route.section = "outra";
    assert.equal(cat.providers[2].settings_route.section, "Apps/music");
    const fallback = sunoSettingsRoute(null);
    fallback.view = "x";
    assert.equal(SUNO_SETTINGS_ROUTE.view, "settings");
  });

  it("sunoSettingsRoute só aceita view settings", () => {
    const cat = catalog(false);
    cat.providers[2].settings_route = { view: "chat", section: "x" };
    assert.deepEqual(sunoSettingsRoute(cat), SUNO_SETTINGS_ROUTE);
    cat.providers[2].settings_route = {
      view: "settings",
      section: "Apps/music2",
    };
    assert.deepEqual(sunoSettingsRoute(cat), {
      view: "settings",
      section: "Apps/music2",
    });
  });

  it("textos de dica, aviso e cancelamento", () => {
    assert.match(SUNO_HINT_TEXT, /Configurações → Música/);
    assert.match(SUNO_REUSE_WARNING, /Configurações → Música/);
    assert.match(SUNO_CANCEL_WARNING, /créditos/);
    assert.match(SUNO_DURATION_HINT, /duração é indicativa/);
  });

  it("generatorHints mostra duração indicativa e créditos só com Suno", () => {
    assert.deepEqual(generatorHints("suno_mcp"), [
      SUNO_DURATION_HINT,
      SUNO_CANCEL_WARNING,
    ]);
    assert.deepEqual(generatorHints("local"), []);
    assert.deepEqual(generatorHints("gemini"), []);
    assert.deepEqual(generatorHints(undefined), []);
  });

  it("partialBatchLabel usa o texto da notificação", () => {
    assert.equal(partialBatchLabel(1, 3), "1 de 3 músicas prontas");
    assert.equal(partialBatchLabel(0, 2), "0 de 2 músicas prontas");
    assert.equal(partialBatchLabel(0, 1), "0 de 1 música pronta");
    assert.equal(partialBatchLabel(undefined, 3), "");
    assert.equal(partialBatchLabel(1, 0), "");
  });

  it("buildGeneratorOptions mantém o provedor atual com keep", () => {
    assert.deepEqual(
      values(buildGeneratorOptions(catalog(false), "suno_mcp")),
      ["local", "gemini", "suno_mcp", "flow"],
    );
    assert.deepEqual(values(buildGeneratorOptions(null, "suno_mcp")), [
      "local",
      "gemini",
      "suno_mcp",
      "flow",
    ]);
    assert.deepEqual(values(buildGeneratorOptions(catalog(false), "xyz")), [
      "local",
      "gemini",
      "flow",
    ]);
    assert.deepEqual(values(buildGeneratorOptions(catalog(false), "local")), [
      "local",
      "gemini",
      "flow",
    ]);
  });

  it("reuse de faixa Suno com catálogo carregando fica pendente, sem aviso", () => {
    for (const loading of [null, undefined, { error: "x" }]) {
      assert.deepEqual(
        resolveReuseProvider({ provider: "suno_mcp" }, loading),
        {
          provider: "suno_mcp",
          warning: null,
          pending: true,
        },
      );
    }
  });

  it("evento de atualização do catálogo", () => {
    assert.equal(MUSIC_PROVIDERS_UPDATED_EVENT, "pia:music-providers-updated");
  });

  it("interruptedProgressLabel prefere o ready_text do backend", () => {
    assert.equal(
      interruptedProgressLabel({
        completed: 2,
        total: 3,
        ready_text: "2 de 3 músicas prontas",
      }),
      "Geração interrompida · 2 de 3 músicas prontas",
    );
    assert.equal(
      interruptedProgressLabel({ ready_text: "  1 de 4 músicas prontas " }),
      "Geração interrompida · 1 de 4 músicas prontas",
    );
  });

  it("interruptedProgressLabel cai no partialBatchLabel sem ready_text", () => {
    assert.equal(
      interruptedProgressLabel({ completed: 1, total: 3 }),
      "Geração interrompida · 1 de 3 músicas prontas",
    );
    assert.equal(
      interruptedProgressLabel({ completed: 1, total: 1, ready_text: "" }),
      "Geração interrompida · 1 de 1 música pronta",
    );
  });

  it("interruptedProgressLabel sem faixa pronta ou sem dados mostra só o título", () => {
    assert.equal(
      interruptedProgressLabel({
        completed: 0,
        total: 3,
        ready_text: "0 de 3 músicas prontas",
      }),
      "Geração interrompida",
    );
    assert.equal(interruptedProgressLabel({}), "Geração interrompida");
    assert.equal(interruptedProgressLabel(null), "Geração interrompida");
    assert.equal(
      interruptedProgressLabel({ completed: "x", total: 3, ready_text: 5 }),
      "Geração interrompida",
    );
  });

  it("finalStateForError usa interrupted com faixa pronta", () => {
    assert.equal(
      finalStateForError({ state: "running" }, { completed: 1, total: 3 }),
      "interrupted",
    );
    assert.equal(finalStateForError(null, { completed: "2" }), "interrupted");
  });

  it("finalStateForError mantém interrupted vindo do progress", () => {
    assert.equal(
      finalStateForError({ state: "interrupted" }, { completed: 0 }),
      "interrupted",
    );
    assert.equal(
      finalStateForError({ state: "interrupted" }, {}),
      "interrupted",
    );
  });

  it("finalStateForError usa error sem faixa pronta", () => {
    assert.equal(
      finalStateForError({ state: "running" }, { completed: 0, total: 3 }),
      "error",
    );
    assert.equal(finalStateForError(null, {}), "error");
    assert.equal(finalStateForError(undefined, undefined), "error");
    assert.equal(
      finalStateForError({ state: "running" }, { completed: "x" }),
      "error",
    );
  });
});

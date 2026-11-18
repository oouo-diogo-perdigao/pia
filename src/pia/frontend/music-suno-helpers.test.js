import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  MUSIC_SETTINGS_ROUTE,
  PIA_SERVER_SETTINGS_ROUTE,
  SUNO_ACCOUNT_REQUIRED_HINT,
  SUNO_LEGACY_QUESTION,
  SUNO_TEXT_ACCOUNT_TAKEN,
  SUNO_TEXT_ALL_EXPIRED,
  SUNO_TEXT_CONNECTION_LOST,
  SUNO_TEXT_JOB_ACTIVE,
  SUNO_TEXT_NOT_CONNECTED,
  SUNO_TEXT_NOT_ORIGIN,
  SUNO_TEXT_SERVER_DOWN,
  SUNO_TEXT_TRACK_UNAVAILABLE,
  SUNO_TEXT_UNPAIRED,
  SUNO_TIMEOUT_TEXT,
  activeJobBlockText,
  buildConnectPayload,
  buildGeneratePayload,
  buildSunoRenameRequest,
  connectResultMessage,
  connectionNotice,
  describeSunoError,
  disconnectConfirmText,
  findActiveSunoJob,
  generateButtonState,
  hasLegacyCredentials,
  legacyCredentialsState,
  normalizeSettingsRoute,
  parseHint,
  pollSunoConnect,
  progressDisplay,
  progressReadyText,
  resolveResumeJob,
  resolveSunoAccountSelection,
  safeAuthUrl,
  shouldPromptLegacyCredentials,
  sunoAccountName,
  sunoAccountStateLabel,
  sunoAccounts,
  sunoErrorRoute,
  sunoErrorText,
  sunoUnavailableHint,
} from "./music-suno-helpers.js";

const account = (id, extra = {}) => ({
  id,
  label: null,
  email: id + "@ex.com",
  name: "Nome " + id,
  credential_state: "configured",
  available: true,
  expires_at: null,
  scopes: ["music.generate"],
  ...extra,
});
const catalogWith = (suno) => ({
  providers: [
    { id: "local", available: true },
    { id: "suno_mcp", label: "Suno", ...suno },
  ],
  selection: { provider: "local" },
});

describe("music-suno-helpers: contas e seletor (RN07/RN09)", () => {
  it("nome de exibição segue label → name → email → id", () => {
    assert.equal(
      sunoAccountName({ id: "a", label: "Apelido", name: "N" }),
      "Apelido",
    );
    assert.equal(
      sunoAccountName({ id: "a", label: " ", name: "N", email: "e" }),
      "N",
    );
    assert.equal(sunoAccountName({ id: "a", email: "e@x" }), "e@x");
    assert.equal(sunoAccountName({ id: 7 }), "7");
    assert.equal(sunoAccountName(null), "");
  });

  it("normaliza contas: configured válida, refresh_failed expirada, unavailable desabilitada", () => {
    const list = sunoAccounts(
      catalogWith({
        accounts: [
          account("a"),
          account("b", {
            credential_state: "refresh_failed",
            available: false,
          }),
          account("c", { credential_state: "unavailable", available: false }),
          account("d", { credential_state: "expired", available: false }),
          null,
          { label: "sem id" },
        ],
      }),
    );
    assert.deepEqual(
      list.map((acc) => [acc.id, acc.usable, acc.expired]),
      [
        ["a", true, false],
        ["b", false, true],
        ["c", false, false],
        ["d", false, true],
      ],
    );
    assert.deepEqual(sunoAccountStateLabel(list[0]), {
      label: "Conectada",
      color: "teal",
    });
    assert.deepEqual(sunoAccountStateLabel(list[1]), {
      label: "Expirada — reconectar",
      color: "orange",
    });
    assert.equal(sunoAccountStateLabel(list[2]).label, "Indisponível");
  });

  it("sem conta válida: mode none e Gerar desabilitado", () => {
    const sel = resolveSunoAccountSelection(catalogWith({ accounts: [] }));
    assert.equal(sel.mode, "none");
    assert.equal(sel.ready, false);
    assert.equal(
      generateButtonState({ provider: "suno_mcp", prompt: "x", selection: sel })
        .enabled,
      false,
    );
  });

  it("1 conta válida: seleção automática com 'Conta Suno: <nome>' (CA01)", () => {
    const sel = resolveSunoAccountSelection(
      catalogWith({
        accounts: [account("a", { label: "Minha" })],
        selected_account_id: "a",
      }),
    );
    assert.equal(sel.mode, "single");
    assert.equal(sel.value, "a");
    assert.equal(sel.text, "Conta Suno: Minha");
    assert.equal(sel.ready, true);
  });

  it("1 válida + 1 expirada: regra de 1 conta, expirada listada desabilitada (CA06)", () => {
    const sel = resolveSunoAccountSelection(
      catalogWith({
        accounts: [
          account("a"),
          account("b", {
            credential_state: "refresh_failed",
            available: false,
          }),
        ],
      }),
    );
    assert.equal(sel.mode, "single");
    assert.equal(sel.value, "a");
    assert.equal(sel.expired.length, 1);
    const disabled = sel.options.find((o) => o.value === "b");
    assert.equal(disabled.disabled, true);
    assert.match(
      disabled.label,
      /expirada — reconecte em Configurações → Música/,
    );
  });

  it("2+ válidas: ignora o selected_account_id do backend e começa vazio (RN09/CA06)", () => {
    const cat = catalogWith({
      accounts: [account("a"), account("b")],
      // O backend preenche com o default_account_id do servidor.
      selected_account_id: "a",
    });
    const sel = resolveSunoAccountSelection(cat, null);
    assert.equal(sel.mode, "multiple");
    assert.equal(sel.value, null);
    assert.equal(sel.ready, false);
    assert.equal(sel.hint, SUNO_ACCOUNT_REQUIRED_HINT);
    const state = generateButtonState({
      provider: "suno_mcp",
      prompt: "x",
      selection: sel,
    });
    assert.deepEqual(state, { enabled: false, hint: "Escolha a conta Suno" });
  });

  it("2+ válidas: só a escolha da sessão vale; conta expirada ou inexistente não", () => {
    const cat = catalogWith({
      accounts: [
        account("a"),
        account("b"),
        account("c", { credential_state: "refresh_failed", available: false }),
      ],
      selected_account_id: "a",
    });
    const chosen = resolveSunoAccountSelection(cat, "b");
    assert.equal(chosen.value, "b");
    assert.equal(chosen.ready, true);
    assert.equal(
      generateButtonState({
        provider: "suno_mcp",
        prompt: "x",
        selection: chosen,
      }).enabled,
      true,
    );
    assert.equal(resolveSunoAccountSelection(cat, "c").value, null);
    assert.equal(resolveSunoAccountSelection(cat, "sumiu").value, null);
    // "Limpar após cada geração" = voltar a chamar com null.
    assert.equal(resolveSunoAccountSelection(cat, null).value, null);
  });

  it("dica 'Escolha a conta Suno' aparece antes do prompt; Gerar exige prompt", () => {
    const cat = catalogWith({ accounts: [account("a"), account("b")] });
    assert.deepEqual(
      generateButtonState({
        provider: "suno_mcp",
        prompt: "",
        selection: resolveSunoAccountSelection(cat, null),
      }),
      { enabled: false, hint: "Escolha a conta Suno" },
    );
    assert.deepEqual(
      generateButtonState({
        provider: "suno_mcp",
        prompt: " ",
        selection: resolveSunoAccountSelection(cat, "a"),
      }),
      { enabled: false, hint: "" },
    );
  });

  it("Gerar: prompt vazio, ocupado e outros provedores", () => {
    assert.equal(
      generateButtonState({ provider: "local", prompt: " " }).enabled,
      false,
    );
    assert.equal(
      generateButtonState({ provider: "local", prompt: "x" }).enabled,
      true,
    );
    assert.equal(
      generateButtonState({ provider: "local", prompt: "x", busy: true })
        .enabled,
      false,
    );
  });
});

describe("music-suno-helpers: body da geração", () => {
  const base = { prompt: "p", lyrics: "", duration: 30, count: 2 };
  it("Suno com 1 conta manda o suno_account_id da seleção automática", () => {
    const sel = resolveSunoAccountSelection(
      catalogWith({ accounts: [account("a")] }),
    );
    assert.deepEqual(
      buildGeneratePayload({
        ...base,
        provider: "suno_mcp",
        sunoAccountId: sel.value,
      }),
      { ...base, provider: "suno_mcp", suno_account_id: "a" },
    );
  });
  it("Suno com 2+ contas manda a conta escolhida", () => {
    assert.equal(
      buildGeneratePayload({
        ...base,
        provider: "suno_mcp",
        sunoAccountId: "b",
      }).suno_account_id,
      "b",
    );
  });
  it("outros provedores não mandam suno_account_id", () => {
    assert.deepEqual(
      buildGeneratePayload({ ...base, provider: "local", sunoAccountId: "a" }),
      {
        ...base,
        provider: "local",
      },
    );
  });
});

describe("music-suno-helpers: job ativo (RN10/RN15)", () => {
  it("lê o active_job do item (contrato real) com suno_account_id", () => {
    const cat = catalogWith({
      accounts: [account("a")],
      active_job: {
        job_id: "j1",
        state: "running",
        this_device: true,
        suno_account_id: "a",
        completed: 1,
        total: 3,
        extra_ready: 0,
      },
    });
    assert.deepEqual(findActiveSunoJob(cat), {
      jobId: "j1",
      state: "running",
      thisDevice: true,
      accountId: "a",
      completed: 1,
      total: 3,
      extraReady: 0,
    });
    assert.equal(resolveResumeJob(cat), "j1");
    assert.equal(resolveResumeJob(cat, "j1"), null);
  });

  it("aceita, por defesa, o active_job dentro de accounts[]", () => {
    const cat = catalogWith({
      accounts: [
        account("a"),
        account("b", { active_job: { job_id: "j2", this_device: false } }),
      ],
    });
    const job = findActiveSunoJob(cat);
    assert.equal(job.jobId, "j2");
    assert.equal(job.accountId, "b");
    assert.equal(job.thisDevice, false);
    assert.equal(resolveResumeJob(cat), null);
  });

  it("ignora job terminal", () => {
    for (const active_job of [
      { job_id: "j", state: "completed" },
      { job_id: "j", state: "interrupted" },
      null,
    ])
      assert.equal(findActiveSunoJob(catalogWith({ active_job })), null);
    assert.equal(findActiveSunoJob(null), null);
  });

  it("job_id null (T6): bloqueia o Gerar, mas não retoma pelo watchJob", () => {
    const cat = catalogWith({
      accounts: [account("a")],
      active_job: {
        job_id: null,
        state: "running",
        this_device: true,
        suno_account_id: "a",
        completed: 0,
        total: 2,
        extra_ready: 0,
      },
    });
    const job = findActiveSunoJob(cat);
    assert.equal(job.jobId, null);
    assert.equal(job.thisDevice, true);
    assert.equal(resolveResumeJob(cat), null);
    assert.equal(resolveResumeJob(cat, null), null);
    assert.equal(activeJobBlockText(cat), SUNO_TEXT_JOB_ACTIVE);
    assert.equal(activeJobBlockText(cat, null), SUNO_TEXT_JOB_ACTIVE);
  });

  it("job ativo bloqueia o Gerar do Suno para qualquer conta, salvo o acompanhado", () => {
    const other = catalogWith({
      accounts: [account("a"), account("b")],
      active_job: {
        job_id: "j1",
        state: "running",
        this_device: false,
        suno_account_id: "a",
      },
    });
    assert.equal(activeJobBlockText(other), SUNO_TEXT_JOB_ACTIVE);
    const sel = resolveSunoAccountSelection(other, "b");
    assert.deepEqual(
      generateButtonState({
        provider: "suno_mcp",
        prompt: "x",
        selection: sel,
        blockText: activeJobBlockText(other),
      }),
      { enabled: false, hint: SUNO_TEXT_JOB_ACTIVE },
    );
    assert.equal(activeJobBlockText(other, "j1"), "");
    assert.equal(activeJobBlockText(catalogWith({})), "");
  });
});

describe("music-suno-helpers: codes e textos", () => {
  it("textos do PO para os codes do contrato", () => {
    assert.equal(sunoErrorText("pia_server_unpaired"), SUNO_TEXT_UNPAIRED);
    assert.equal(
      sunoErrorText("pia_server_unreachable"),
      SUNO_TEXT_SERVER_DOWN,
    );
    assert.equal(
      sunoErrorText("pia_server_unsupported"),
      SUNO_TEXT_SERVER_DOWN,
    );
    assert.equal(sunoErrorText("suno_not_connected"), SUNO_TEXT_NOT_CONNECTED);
    assert.equal(
      sunoErrorText("suno_account_required"),
      "Escolha a conta Suno",
    );
    assert.equal(sunoErrorText("suno_account_taken"), SUNO_TEXT_ACCOUNT_TAKEN);
    assert.equal(sunoErrorText("suno_job_active"), SUNO_TEXT_JOB_ACTIVE);
    assert.equal(
      sunoErrorText("suno_track_unavailable"),
      SUNO_TEXT_TRACK_UNAVAILABLE,
    );
    assert.equal(
      SUNO_TEXT_TRACK_UNAVAILABLE,
      "Esta música não está mais disponível no Suno.",
    );
    assert.equal(
      sunoErrorText("suno_unavailable"),
      "Suno indisponível no momento, tente de novo ou use outro gerador",
    );
    assert.equal(
      sunoErrorText("suno_timeout"),
      "O Suno não respondeu a tempo; a geração pode ter sido concluída lá",
    );
    assert.equal(
      sunoErrorText("download_failed"),
      "Não foi possível baixar a música. Tente de novo pelo Histórico.",
    );
  });

  it("expirada e sem créditos citam o nome da conta (RN11)", () => {
    assert.equal(
      sunoErrorText("suno_credential_expired", { accountName: "Ana" }),
      "A autorização da conta Suno Ana expirou. Reconecte em Configurações → Música",
    );
    assert.equal(
      sunoErrorText("suno_credential_expired"),
      SUNO_TEXT_ALL_EXPIRED,
    );
    for (const code of ["insufficient_credits", "suno_no_credits"])
      assert.equal(
        sunoErrorText(code, { accountName: "Ana" }),
        "A conta Suno Ana está sem créditos.",
      );
  });

  it("codes novos do contrato real têm texto próprio", () => {
    for (const code of [
      "suno_connect_not_found",
      "suno_oauth_denied",
      "suno_oauth_invalid",
      "suno_account_not_found",
      "suno_account_mismatch",
      "suno_identity_unavailable",
    ]) {
      const text = sunoErrorText(code, { fallback: "backend" });
      assert.ok(
        text &&
          text !== "backend" &&
          text !== "Algo deu errado. Tente de novo.",
        code,
      );
    }
  });

  it("not_origin_device vira mensagem genérica; desconhecido usa o fallback", () => {
    assert.equal(sunoErrorText("not_origin_device"), SUNO_TEXT_NOT_ORIGIN);
    assert.equal(
      sunoErrorText("xyz", { fallback: "texto do backend" }),
      "texto do backend",
    );
    assert.equal(sunoErrorText(null), "Algo deu errado. Tente de novo.");
  });

  it("atalhos: não pareado → PIA Server; conta → Música", () => {
    assert.deepEqual(
      sunoErrorRoute("pia_server_unpaired"),
      PIA_SERVER_SETTINGS_ROUTE,
    );
    assert.deepEqual(
      sunoErrorRoute("suno_credential_expired"),
      MUSIC_SETTINGS_ROUTE,
    );
    assert.equal(sunoErrorRoute("pia_server_unreachable"), null);
    const route = sunoErrorRoute("pia_server_unpaired");
    route.section = "x";
    assert.equal(PIA_SERVER_SETTINGS_ROUTE.section, "Connectors/pia_server");
  });

  it("describeSunoError lê o erro do api() e o evento de erro do job", () => {
    const err = Object.assign(new Error("Conta expirou (backend)"), {
      code: "suno_credential_expired",
      details: { hint: { text: "fallback" } },
    });
    assert.deepEqual(describeSunoError(err, { accountName: "Bia" }), {
      code: "suno_credential_expired",
      text: "A autorização da conta Suno Bia expirou. Reconecte em Configurações → Música",
      route: MUSIC_SETTINGS_ROUTE,
    });
    const unknown = Object.assign(new Error("msg"), {
      code: "outro",
      details: { hint: { text: "dica do backend" } },
    });
    assert.equal(describeSunoError(unknown).text, "dica do backend");
    assert.equal(
      describeSunoError({ type: "error", error: "Falhou", code: null }).text,
      "Falhou",
    );
  });
});

describe("music-suno-helpers: dica RN02", () => {
  it("sem catálogo ou com Suno disponível não mostra dica", () => {
    assert.equal(sunoUnavailableHint(null), null);
    assert.equal(sunoUnavailableHint(catalogWith({ available: true })), null);
  });
  it("um texto e um atalho por motivo (CA02)", () => {
    const hint = (suno) =>
      sunoUnavailableHint(catalogWith({ available: false, ...suno }));
    assert.deepEqual(hint({ reason: "pia_server_unpaired" }), {
      text: SUNO_TEXT_UNPAIRED,
      route: PIA_SERVER_SETTINGS_ROUTE,
    });
    assert.deepEqual(hint({ reason: "suno_not_connected" }), {
      text: SUNO_TEXT_NOT_CONNECTED,
      route: MUSIC_SETTINGS_ROUTE,
    });
    assert.deepEqual(hint({ reason: "suno_credential_expired" }), {
      text: SUNO_TEXT_ALL_EXPIRED,
      route: MUSIC_SETTINGS_ROUTE,
    });
    assert.deepEqual(hint({ reason: "pia_server_unreachable" }), {
      text: SUNO_TEXT_SERVER_DOWN,
      route: null,
    });
    assert.deepEqual(hint({ reason: "pia_server_unsupported" }).route, null);
    assert.equal(
      hint({
        reason: null,
        accounts: [
          account("a", {
            credential_state: "refresh_failed",
            available: false,
          }),
        ],
      }).text,
      SUNO_TEXT_ALL_EXPIRED,
    );
  });
  it("usa o hint.route do backend quando válido (objeto)", () => {
    const hint = sunoUnavailableHint(
      catalogWith({
        available: false,
        reason: "suno_not_connected",
        hint: {
          text: "x",
          route: { view: "settings", section: "Apps/music2" },
        },
      }),
    );
    assert.deepEqual(hint.route, { view: "settings", section: "Apps/music2" });
    assert.equal(hint.text, SUNO_TEXT_NOT_CONNECTED);
    assert.equal(normalizeSettingsRoute({ view: "chat", section: "x" }), null);
    assert.deepEqual(
      normalizeSettingsRoute("settings/pia_server"),
      PIA_SERVER_SETTINGS_ROUTE,
    );
    assert.equal(normalizeSettingsRoute(null), null);
  });
});

describe("music-suno-helpers: connect assíncrono (RN06/CA04/CA07)", () => {
  function clock() {
    let t = 0;
    return {
      now: () => t,
      sleep: async (ms) => {
        t += ms;
      },
    };
  }

  it("faz polling a cada 3 s até connected", async () => {
    const c = clock();
    const calls = [];
    const states = ["pending", "pending", "connected"];
    const result = await pollSunoConnect({
      attemptId: "at1",
      expiresIn: 600,
      fetchState: async (id) => {
        calls.push([id, c.now()]);
        const state = states.shift();
        return state === "connected" ? { state, account_id: 9 } : { state };
      },
      ...c,
    });
    assert.deepEqual(result, { state: "connected", account_id: "9" });
    assert.deepEqual(calls, [
      ["at1", 3000],
      ["at1", 6000],
      ["at1", 9000],
    ]);
  });

  it("failed traz o code (suno_account_taken → RN08)", async () => {
    const result = await pollSunoConnect({
      attemptId: "a",
      fetchState: async () => ({ state: "failed", code: "suno_account_taken" }),
      ...clock(),
    });
    assert.deepEqual(result, { state: "failed", code: "suno_account_taken" });
    assert.deepEqual(connectResultMessage(result), {
      ok: false,
      text: SUNO_TEXT_ACCOUNT_TAKEN,
      color: "red",
    });
  });

  it("estoura o expires_in com 'Tempo esgotado, tente de novo'", async () => {
    const c = clock();
    let calls = 0;
    const result = await pollSunoConnect({
      attemptId: "a",
      expiresIn: 9,
      fetchState: async () => {
        calls += 1;
        return { state: "pending" };
      },
      ...c,
    });
    assert.deepEqual(result, { state: "expired" });
    assert.equal(calls, 3);
    assert.equal(connectResultMessage(result).text, SUNO_TIMEOUT_TEXT);
  });

  it("erro de rede no polling não encerra; connect_not_found e unpaired encerram", async () => {
    let n = 0;
    const flaky = await pollSunoConnect({
      attemptId: "a",
      fetchState: async () => {
        n += 1;
        if (n === 1) throw new Error("rede");
        return { state: "connected" };
      },
      ...clock(),
    });
    assert.equal(flaky.state, "connected");
    for (const code of ["suno_connect_not_found", "pia_server_unpaired"]) {
      const res = await pollSunoConnect({
        attemptId: "a",
        fetchState: async () => {
          throw Object.assign(new Error("x"), { code });
        },
        ...clock(),
      });
      assert.deepEqual(res, { state: "failed", code });
    }
  });

  it("cancelar para o polling", async () => {
    let cancelled = false;
    const res = await pollSunoConnect({
      attemptId: "a",
      fetchState: async () => {
        cancelled = true;
        return { state: "pending" };
      },
      isCancelled: () => cancelled,
      ...clock(),
    });
    assert.deepEqual(res, { state: "cancelled" });
    assert.equal(connectResultMessage(res).text, "");
  });

  it("mensagens finais e payload do connect", () => {
    assert.equal(connectResultMessage({ state: "connected" }).ok, true);
    assert.equal(
      connectResultMessage({ state: "failed", code: "suno_oauth_denied" }).text,
      sunoErrorText("suno_oauth_denied"),
    );
    assert.match(
      connectResultMessage({ state: "failed" }).text,
      /Não foi possível conectar/,
    );
    assert.deepEqual(buildConnectPayload(), {});
    assert.deepEqual(buildConnectPayload("acc"), { replace_account_id: "acc" });
    assert.equal(
      safeAuthUrl("https://suno.com/oauth?x=1"),
      "https://suno.com/oauth?x=1",
    );
    assert.equal(safeAuthUrl("javascript:alert(1)"), null);
    assert.equal(safeAuthUrl(undefined), null);
    assert.match(
      disconnectConfirmText({ id: "a", label: "Ana" }),
      /Desconectar a conta Suno Ana\?/,
    );
  });
});

describe("music-suno-helpers: apelido, credenciais antigas e progresso", () => {
  it("apelido usa a rota única (POST /music/suno/accounts/<id>/rename)", () => {
    assert.deepEqual(
      buildSunoRenameRequest({ id: "a b", label: "Velho" }, "  Novo "),
      {
        path: "/music/suno/accounts/a%20b/rename",
        method: "POST",
        data: { label: "Novo" },
      },
    );
    assert.equal(
      buildSunoRenameRequest({ id: "a", label: "Igual" }, "Igual"),
      null,
    );
    assert.equal(buildSunoRenameRequest({ id: "a" }, "  "), null);
    assert.equal(buildSunoRenameRequest(null, "x"), null);
  });

  it("pergunta do RN21 só com present e prompt", () => {
    assert.equal(
      shouldPromptLegacyCredentials({ present: true, prompt: true }),
      true,
    );
    assert.equal(
      shouldPromptLegacyCredentials({ present: true, prompt: false }),
      false,
    );
    assert.equal(shouldPromptLegacyCredentials(null), false);
    assert.equal(hasLegacyCredentials({ present: true, prompt: false }), true);
    assert.equal(hasLegacyCredentials({ present: false }), false);
    assert.match(
      SUNO_LEGACY_QUESTION,
      /Remover as credenciais antigas do Suno deste computador\?$/,
    );
  });

  it("ready_text do backend ou calculado com extra (RN12)", () => {
    assert.equal(progressReadyText({ ready_text: " pronto " }), "pronto");
    assert.equal(
      progressReadyText({ completed: 3, total: 3, extra_ready: 1 }),
      "3 de 3 músicas prontas (+1 extra)",
    );
    assert.equal(
      progressReadyText({ completed: 1, total: 3 }),
      "1 de 3 músicas prontas",
    );
    assert.equal(progressReadyText({}), "");
  });

  it("progressDisplay troca o label só com ready_text ou extras", () => {
    const plain = { label: "Gerando música 1/2", completed: 0, total: 2 };
    assert.equal(progressDisplay(plain), plain);
    assert.equal(
      progressDisplay({ ...plain, completed: 2, extra_ready: 1, total: 2 })
        .label,
      "2 de 2 músicas prontas (+1 extra)",
    );
    assert.equal(progressDisplay({ ...plain, ready_text: "R" }).label, "R");
    assert.equal(progressDisplay(null), null);
  });

  it("connection lost mostra o aviso do RN11 sem encerrar", () => {
    assert.equal(
      connectionNotice({ connection: "lost" }),
      SUNO_TEXT_CONNECTION_LOST,
    );
    assert.equal(connectionNotice({ connection: "ok" }), "");
    assert.equal(connectionNotice(null), "");
  });
});

describe("music-suno-helpers: formatos finais da T6 (435c4cd)", () => {
  it("parseHint aceita objeto e string", () => {
    assert.deepEqual(
      parseHint({
        text: " t ",
        route: { view: "settings", section: "Apps/music" },
      }),
      {
        text: "t",
        route: { view: "settings", section: "Apps/music" },
        explicitRoute: true,
      },
    );
    assert.deepEqual(parseHint({ text: "t", route: null }), {
      text: "t",
      route: null,
      explicitRoute: true,
    });
    assert.deepEqual(parseHint("só texto"), {
      text: "só texto",
      route: null,
      explicitRoute: false,
    });
    assert.deepEqual(parseHint(null), {
      text: "",
      route: null,
      explicitRoute: false,
    });
  });

  it("hint.route null do backend: dica sem atalho", () => {
    const hint = sunoUnavailableHint(
      catalogWith({
        available: false,
        reason: "suno_not_connected",
        hint: {
          text: "Conecte o Suno em Configurações → Música.",
          route: null,
        },
      }),
    );
    assert.deepEqual(hint, { text: SUNO_TEXT_NOT_CONNECTED, route: null });
  });

  it("hint string (defesa): mantém o atalho padrão do motivo", () => {
    const hint = sunoUnavailableHint(
      catalogWith({
        available: false,
        reason: "pia_server_unpaired",
        hint: "texto antigo",
      }),
    );
    assert.deepEqual(hint, {
      text: SUNO_TEXT_UNPAIRED,
      route: PIA_SERVER_SETTINGS_ROUTE,
    });
  });

  it("hint do item na T6 para não pareado traz o route da PIA Server", () => {
    const hint = sunoUnavailableHint(
      catalogWith({
        available: false,
        reason: "pia_server_unpaired",
        hint: { text: "x", route: { ...PIA_SERVER_SETTINGS_ROUTE } },
      }),
    );
    assert.deepEqual(hint.route, PIA_SERVER_SETTINGS_ROUTE);
  });

  it("conta indisponível traz reason e hint (texto em hintText)", () => {
    const [acc] = sunoAccounts(
      catalogWith({
        accounts: [
          account("x", {
            credential_state: "unavailable",
            available: false,
            reason: "suno_credential_expired",
            hint: {
              text: "A conexão com o Suno expirou. Reconecte em Configurações → Música.",
              route: { view: "settings", section: "Apps/music" },
            },
          }),
        ],
      }),
    );
    assert.equal(acc.usable, false);
    assert.equal(acc.expired, true);
    assert.equal(acc.reason, "suno_credential_expired");
    assert.match(acc.hintText, /expirou/);
    assert.equal(
      sunoAccounts(catalogWith({ accounts: [account("y")] }))[0].hintText,
      "",
    );
  });

  it("invalid_label usa a mensagem do backend", () => {
    const err = Object.assign(
      new Error(
        "O apelido da conta Suno deve ter de 1 a 80 caracteres, sem caracteres de controle.",
      ),
      { code: "invalid_label", details: {} },
    );
    assert.match(describeSunoError(err).text, /de 1 a 80 caracteres/);
  });
});

describe("music-suno-helpers: textos do Anexo A do PO", () => {
  it("codes do connect e da conta com o texto exato do PO", () => {
    assert.equal(
      sunoErrorText("suno_account_mismatch", { accountName: "Ana" }),
      "A conta autorizada no Suno é diferente da conta Ana que você pediu para reconectar. Entre no Suno com a conta Ana e tente de novo.",
    );
    assert.equal(
      sunoErrorText("suno_account_mismatch"),
      "A conta autorizada no Suno é diferente da que você pediu para reconectar. Entre no Suno com a conta certa e tente de novo.",
    );
    assert.equal(
      sunoErrorText("suno_identity_unavailable"),
      "O Suno não informou qual conta foi autorizada, então nenhuma conta foi conectada. Tente de novo.",
    );
    // O texto do PO vale mais que o do backend.
    assert.equal(
      sunoErrorText("suno_connect_not_found", {
        fallback:
          "Tentativa de conexão não encontrada. Tente conectar de novo.",
      }),
      "Esta tentativa de conexão expirou. Clique em Conectar conta Suno para começar de novo.",
    );
    assert.equal(
      sunoErrorText("suno_oauth_denied"),
      "A autorização foi cancelada no Suno. Nenhuma conta foi conectada.",
    );
    assert.equal(
      sunoErrorText("suno_oauth_invalid"),
      "Não foi possível concluir a autorização com o Suno. Tente conectar de novo.",
    );
    assert.equal(
      sunoErrorText("suno_account_not_found"),
      "Esta conta Suno não está mais conectada. Escolha outra conta ou reconecte em Configurações → Música.",
    );
    assert.deepEqual(
      sunoErrorRoute("suno_account_not_found"),
      MUSIC_SETTINGS_ROUTE,
    );
    assert.equal(
      sunoErrorText("not_origin_device"),
      'Esta geração foi iniciada em outro computador. Use "Baixar novamente" no Histórico para trazer as músicas para cá.',
    );
    assert.equal(sunoErrorRoute("not_origin_device"), null);
    assert.equal(
      sunoErrorText("codigo_novo"),
      "Algo deu errado. Tente de novo.",
    );
  });

  it("mismatch no Reconectar cita a conta pedida", () => {
    assert.equal(
      connectResultMessage(
        { state: "failed", code: "suno_account_mismatch" },
        { accountName: "Bia" },
      ).text,
      "A conta autorizada no Suno é diferente da conta Bia que você pediu para reconectar. Entre no Suno com a conta Bia e tente de novo.",
    );
  });

  it("confirmação do Desconectar com o nome da conta", () => {
    assert.equal(
      disconnectConfirmText({ id: "a", label: "Ana", name: "N" }),
      "Desconectar a conta Suno Ana? Ela não poderá mais ser usada para gerar músicas em nenhum computador desta conta PIA. As músicas já baixadas e o histórico continuam como estão.",
    );
    assert.match(
      disconnectConfirmText({ id: "x", email: "e@x" }),
      /^Desconectar a conta Suno e@x\?/,
    );
  });
});

describe("music-suno-helpers: credenciais antigas no catálogo (T8)", () => {
  it("lê legacy_credentials do item suno_mcp", () => {
    assert.deepEqual(
      legacyCredentialsState(
        catalogWith({ legacy_credentials: { present: true, prompt: true } }),
      ),
      { present: true, prompt: true },
    );
    assert.deepEqual(
      legacyCredentialsState(
        catalogWith({ legacy_credentials: { present: false, prompt: true } }),
      ),
      { present: false, prompt: false },
    );
    assert.deepEqual(legacyCredentialsState(catalogWith({})), {
      present: false,
      prompt: false,
    });
    assert.deepEqual(
      legacyCredentialsState({ present: true, prompt: false, items: [] }),
      { present: true, prompt: false },
    );
    assert.deepEqual(legacyCredentialsState(null), {
      present: false,
      prompt: false,
    });
  });

  it("até a T6, pia_server_unsupported mostra a dica de servidor (RN02)", () => {
    const hint = sunoUnavailableHint(
      catalogWith({ available: false, reason: "pia_server_unsupported" }),
    );
    assert.deepEqual(hint, { text: SUNO_TEXT_SERVER_DOWN, route: null });
    assert.equal(
      resolveSunoAccountSelection(
        catalogWith({ available: false, reason: "pia_server_unsupported" }),
      ).mode,
      "none",
    );
  });
});

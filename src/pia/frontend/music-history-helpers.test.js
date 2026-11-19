import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  HISTORY_DELETE_CONFIRM,
  HISTORY_EMPTY_TEXT,
  HISTORY_STATE_RUNNING,
  HISTORY_OTHER_DEVICE_LOCAL_TEXT,
  HISTORY_UNAVAILABLE_TEXT,
  applyHistoryPage,
  historyDateLabel,
  historyFilePath,
  historyFromLibrary,
  historyGeneratorLabel,
  historyNotice,
  historyPath,
  historyStateLabel,
  historyTrackAction,
  historyTrackLabel,
  historyTrackTitle,
  isActiveHistoryItem,
  mergeHistoryPages,
  normalizeHistoryPage,
  removeHistoryItem,
  replaceHistoryTrack,
  reuseFromHistory,
  trackFromRedownloadEvent,
  historyDeleteErrorMessage,
  visibleHistoryItems,
} from "./music-history-helpers.js";
import { SUNO_REUSE_WARNING } from "./music-helpers.js";
import {
  GENERIC_ERROR_TEXT,
  PIA_SERVER_SETTINGS_ROUTE,
  SUNO_TEXT_SERVER_DOWN,
  SUNO_TEXT_UNPAIRED,
  describeSunoError,
} from "./music-suno-helpers.js";

const file = (name) => ({
  file: name,
  audio_url: "/api/pia/music/files/" + name,
  provider: "suno_mcp",
});
const item = (id, extra = {}) => ({
  id,
  job_id: "job-" + id,
  provider: "suno_mcp",
  source: "suno",
  suno_account: { id: "a", name: "Ana" },
  prompt: "rock " + id,
  lyrics: "la la",
  params: {
    provider: "suno_mcp",
    suno_account_id: "a",
    duration: 60,
    count: 1,
  },
  state: "done",
  code: null,
  count: 1,
  created_at: "2026-11-17T23:00:00Z",
  this_device: true,
  tracks: [
    {
      n: 1,
      title: "T1",
      extra: false,
      label: "Suno",
      availability: "local_file",
      file: file("a.mp3"),
    },
    {
      n: 2,
      title: "",
      extra: true,
      label: "Suno · extra",
      availability: "redownload",
    },
  ],
  ...extra,
});

describe("music-history-helpers: páginas", () => {
  it("monta a URL com cursor e limit=100", () => {
    assert.equal(historyPath(), "/music/history?limit=100");
    assert.equal(
      historyPath("c/1 2"),
      "/music/history?cursor=c%2F1+2&limit=100",
    );
  });

  it("normaliza a resposta e descarta itens inválidos", () => {
    const page = normalizeHistoryPage({
      items: [
        item("1"),
        null,
        { prompt: "sem id" },
        { id: 5, tracks: [{ title: "x" }, null] },
      ],
      next_cursor: "abc",
      server_unavailable: false,
      server_reason: null,
    });
    assert.deepEqual(
      page.items.map((i) => i.id),
      ["1", "5"],
    );
    assert.deepEqual(page.items[1].tracks, [{ title: "x", n: 1 }]);
    assert.deepEqual(page.items[1].params, {});
    assert.equal(page.nextCursor, "abc");
    assert.equal(normalizeHistoryPage(null).nextCursor, null);
    assert.deepEqual(normalizeHistoryPage(undefined).items, []);
  });

  it("Carregar mais acrescenta sem duplicar; a 1ª página substitui", () => {
    let state = applyHistoryPage(null, {
      items: [item("1"), item("2")],
      next_cursor: "c1",
    });
    state = applyHistoryPage(
      state,
      { items: [item("2", { prompt: "novo" }), item("3")], next_cursor: null },
      { append: true },
    );
    assert.deepEqual(
      state.items.map((i) => i.id),
      ["1", "2", "3"],
    );
    assert.equal(state.items[1].prompt, "novo");
    assert.equal(state.nextCursor, null);
    state = applyHistoryPage(state, { items: [item("9")] });
    assert.deepEqual(
      state.items.map((i) => i.id),
      ["9"],
    );
  });

  it("jobs ativos ficam no topo (RN25)", () => {
    const merged = mergeHistoryPages(
      [item("1"), item("2")],
      [item("3", { state: "running" })],
    );
    assert.deepEqual(
      merged.map((i) => i.id),
      ["3", "1", "2"],
    );
    assert.equal(isActiveHistoryItem({ state: "queued" }), true);
    assert.equal(isActiveHistoryItem({ state: "done" }), false);
  });

  it("remove item e troca só a faixa atualizada", () => {
    const items = normalizeHistoryPage({ items: [item("1"), item("2")] }).items;
    assert.deepEqual(
      removeHistoryItem(items, "1").map((i) => i.id),
      ["2"],
    );
    const updated = replaceHistoryTrack(items, "1", 2, {
      availability: "local_file",
      file: file("b.mp3"),
    });
    assert.equal(updated[0].tracks[1].availability, "local_file");
    assert.equal(updated[0].tracks[1].label, "Suno · extra");
    assert.equal(updated[0].tracks[0], items[0].tracks[0]);
    assert.equal(updated[1], items[1]);
    assert.equal(replaceHistoryTrack(items, "1", 2, null), items);
  });
});

describe("music-history-helpers: evento track do redownload", () => {
  it("aceita {track}, {item} faixa e {item} da biblioteca", () => {
    assert.deepEqual(
      trackFromRedownloadEvent({
        track: { n: 2, availability: "local_file", file: file("b.mp3") },
      }),
      { n: 2, availability: "local_file", file: file("b.mp3") },
    );
    assert.deepEqual(
      trackFromRedownloadEvent({ item: { n: 1, file: file("c.mp3") } }),
      {
        n: 1,
        file: file("c.mp3"),
        availability: "local_file",
      },
    );
    assert.deepEqual(trackFromRedownloadEvent({ item: file("d.mp3") }), {
      availability: "local_file",
      file: file("d.mp3"),
    });
    assert.equal(trackFromRedownloadEvent({ item: { foo: 1 } }), null);
    assert.equal(trackFromRedownloadEvent({}), null);
  });
  it("formatos reais da T6 (a19ccb6): track {item, track, history_id} e done {result}", () => {
    const payload = {
      n: 2,
      title: "B+",
      duration: 20,
      extra: true,
      label: "Suno · extra",
      availability: "local_file",
      file: file("e.mp3"),
    };
    // `item` é o arquivo da biblioteca; a faixa vem em `track`.
    assert.deepEqual(
      trackFromRedownloadEvent({
        type: "track",
        item: file("e.mp3"),
        track: payload,
        history_id: "h-1",
      }),
      payload,
    );
    assert.deepEqual(
      trackFromRedownloadEvent({
        type: "done",
        result: { track: payload, history_id: "h-1" },
      }),
      payload,
    );
    assert.equal(trackFromRedownloadEvent({ type: "done", result: {} }), null);
  });
});

describe("music-history-helpers: ação por availability (RN25/RN16)", () => {
  it("local_file toca e abre pasta", () => {
    const action = historyTrackAction({
      availability: "local_file",
      file: file("a.mp3"),
    });
    assert.equal(action.kind, "local");
    assert.equal(action.url, "/api/pia/music/files/a.mp3");
    assert.deepEqual(historyTrackAction({ availability: "local_file" }), {
      kind: "none",
    });
  });
  it("redownload oferece Baixar novamente (exceto offline)", () => {
    assert.deepEqual(historyTrackAction({ availability: "redownload" }), {
      kind: "redownload",
    });
    assert.deepEqual(
      historyTrackAction(
        { availability: "redownload" },
        { serverUnavailable: true },
      ),
      { kind: "none" },
    );
  });
  it("other_device_local mostra 'Áudio no computador que gerou'", () => {
    assert.deepEqual(
      historyTrackAction({ availability: "other_device_local" }),
      {
        kind: "text",
        text: HISTORY_OTHER_DEVICE_LOCAL_TEXT,
      },
    );
    assert.equal(
      HISTORY_OTHER_DEVICE_LOCAL_TEXT,
      "Áudio no computador que gerou",
    );
  });
  it("áudio local apagado (T6): availability null e file null, sem ação", () => {
    assert.deepEqual(historyTrackAction({ availability: null, file: null }), {
      kind: "none",
    });
    const page = normalizeHistoryPage({
      items: [
        {
          id: "z",
          provider: "local",
          suno_account: null,
          tracks: [{ n: 1, availability: null, file: null }],
        },
      ],
    });
    assert.equal(page.items[0].suno_account, null);
    assert.equal(historyTrackTitle(page.items[0].tracks[0]), "Versão 1");
    assert.equal(historyTrackLabel(page.items[0].tracks[0]), "");
  });

  it("evento track do redownload da T6 ({item, track, history_id})", () => {
    const payload = {
      n: 2,
      title: "T",
      extra: true,
      label: "Suno · extra",
      availability: "local_file",
      file: file("b.mp3"),
    };
    assert.deepEqual(
      trackFromRedownloadEvent({
        type: "track",
        item: payload.file,
        track: payload,
        history_id: "1",
      }),
      payload,
    );
  });

  it("RN16: not_origin_device não bloqueia nem esconde o Baixar novamente", () => {
    const items = normalizeHistoryPage({
      items: [item("1", { this_device: false })],
    }).items;
    const track = items[0].tracks[1];
    assert.deepEqual(historyTrackAction(track), { kind: "redownload" });
    // Depois de um erro not_origin_device, a lista e a ação não mudam:
    // o Panel só mostra a mensagem e libera o botão.
    const error = describeSunoError({
      type: "error",
      error: "x",
      code: "not_origin_device",
    });
    assert.equal(
      error.text,
      "O áudio desta música ficou no computador que a gerou e não pode ser baixado aqui.",
    );
    assert.equal(error.route, null);
    const after = replaceHistoryTrack(
      items,
      "1",
      2,
      trackFromRedownloadEvent({ type: "error" }),
    );
    assert.equal(after, items);
    assert.deepEqual(historyTrackAction(after[0].tracks[1]), {
      kind: "redownload",
    });
  });

  it("valor desconhecido (inclusive o other_device_suno removido) não tem ação", () => {
    for (const availability of ["other_device_suno", "xyz", undefined, null])
      assert.deepEqual(historyTrackAction({ availability }), { kind: "none" });
    assert.deepEqual(historyTrackAction(null), { kind: "none" });
  });
  it("caminho do reveal-file", () => {
    assert.equal(
      historyFilePath({ path: "C:/m/a.mp3", file: "a.mp3" }, "x"),
      "C:/m/a.mp3",
    );
    assert.equal(
      historyFilePath(file("a.mp3"), "C:\\Música\\PIA\\"),
      "C:\\Música\\PIA/a.mp3",
    );
    assert.equal(historyFilePath(file("a.mp3"), ""), null);
    assert.equal(historyFilePath(null, "x"), null);
  });
});

describe("music-history-helpers: rótulos (RN25)", () => {
  it("gerador, faixa e título", () => {
    assert.equal(historyGeneratorLabel({ provider: "suno_mcp" }), "Suno");
    assert.equal(
      historyGeneratorLabel({ provider: "local" }),
      "Local · ACE-Step",
    );
    assert.equal(historyGeneratorLabel({ provider: "gemini" }), "Gemini");
    assert.equal(historyGeneratorLabel({ source: "suno" }), "Suno");
    assert.equal(historyGeneratorLabel({ provider: "novo" }), "novo");
    assert.equal(
      historyTrackLabel({ extra: true, label: "Suno" }),
      "Suno · extra",
    );
    assert.equal(historyTrackLabel({ extra: false, label: "Suno" }), "Suno");
    assert.equal(historyTrackLabel({}), "");
    assert.equal(historyTrackTitle({ n: 2, title: " " }), "Versão 2");
    assert.equal(historyTrackTitle({ n: 1, title: "Canção" }), "Canção");
  });

  it("estado final: Concluída, k de N, Interrompida, Cancelada", () => {
    const norm = (x) => normalizeHistoryPage({ items: [x] }).items[0];
    assert.equal(historyStateLabel(norm(item("1"))), "Concluída");
    assert.equal(
      historyStateLabel(norm(item("1", { state: "cancelled" }))),
      "Cancelada",
    );
    assert.equal(
      historyStateLabel(norm(item("1", { state: "interrupted", count: 3 }))),
      "1 de 3 músicas prontas",
    );
    assert.equal(
      historyStateLabel(
        norm(item("1", { state: "error", count: 3, tracks: [] })),
      ),
      "Interrompida",
    );
    assert.equal(
      historyStateLabel(norm(item("1", { state: "interrupted", count: 1 }))),
      "Interrompida",
    );
  });

  it("em andamento usa o progresso atual", () => {
    const running = normalizeHistoryPage({
      items: [item("1", { state: "running", count: 3, tracks: [] })],
    }).items[0];
    assert.equal(
      historyStateLabel(running),
      "Em andamento · 0 de 3 músicas prontas",
    );
    assert.equal(
      historyStateLabel(running, {
        label: "2 de 3 músicas prontas (+1 extra)",
      }),
      "2 de 3 músicas prontas (+1 extra)",
    );
  });

  it("data em pt-BR e entrada inválida vazia", () => {
    assert.match(
      historyDateLabel("2026-11-17T23:00:00Z"),
      /17\/11\/2026|\d{2}\/\d{2}\/\d{4}/,
    );
    assert.notEqual(historyDateLabel(1763420400), "");
    assert.equal(historyDateLabel("nada"), "");
    assert.equal(historyDateLabel(null), "");
  });
});

describe("music-history-helpers: offline (RN25)", () => {
  it("aviso do PO; atalho só quando não pareado", () => {
    assert.equal(historyNotice({ serverUnavailable: false }), null);
    assert.deepEqual(
      historyNotice({
        serverUnavailable: true,
        serverReason: "pia_server_unreachable",
      }),
      {
        text: HISTORY_UNAVAILABLE_TEXT,
        route: null,
      },
    );
    assert.deepEqual(
      historyNotice({
        serverUnavailable: true,
        serverReason: "pia_server_unpaired",
      }).route,
      {
        view: "settings",
        section: "Connectors/pia_server",
      },
    );
    assert.equal(
      HISTORY_UNAVAILABLE_TEXT,
      "Histórico da conta indisponível agora; mostrando só as músicas deste computador.",
    );
  });

  it("offline mostra só itens e faixas deste PC", () => {
    const page = normalizeHistoryPage({
      items: [item("1"), item("2", { this_device: false })],
      server_unavailable: true,
    });
    const visible = visibleHistoryItems(page);
    assert.deepEqual(
      visible.map((i) => i.id),
      ["1"],
    );
    assert.deepEqual(
      visible[0].tracks.map((t) => t.n),
      [1],
    );
    const online = normalizeHistoryPage({
      items: [item("1"), item("2", { this_device: false })],
    });
    assert.equal(visibleHistoryItems(online).length, 2);
  });

  it("texto da exclusão diz que o arquivo local fica e some em todos os PCs", () => {
    assert.equal(
      HISTORY_DELETE_CONFIRM,
      "Excluir esta geração do histórico? O prompt, a letra e os links serão apagados da PIA Server e o item some em todos os computadores da conta. Os arquivos de música deste computador continuam na pasta Música/PIA. Não dá para desfazer.",
    );
    assert.equal(HISTORY_STATE_RUNNING, "Em andamento");
    assert.equal(HISTORY_EMPTY_TEXT, "Nenhuma música gerada ainda.");
  });
});

describe("music-history-helpers: Reutilizar prompt (RN18/RN09/CA21)", () => {
  const catalog = (accounts, available = true) => ({
    providers: [
      { id: "local", available: true },
      { id: "suno_mcp", available, accounts },
    ],
  });
  const acc = (id) => ({
    id,
    name: id,
    credential_state: "configured",
    available: true,
  });

  it("preenche o Gerador a partir do params", () => {
    const out = reuseFromHistory(
      item("1", {
        params: {
          provider: "suno_mcp",
          suno_account_id: "a",
          duration: 500,
          count: 3,
          prompt: "do params",
        },
      }),
      catalog([acc("a")]),
    );
    assert.deepEqual(out, {
      prompt: "do params",
      lyrics: "la la",
      provider: "suno_mcp",
      warning: null,
      pending: false,
      duration: 180,
      count: 3,
      sunoAccountId: "a",
    });
  });

  it("com 2+ contas não pré-seleciona a conta, nem a do item", () => {
    const out = reuseFromHistory(item("1"), catalog([acc("a"), acc("b")]));
    assert.equal(out.provider, "suno_mcp");
    assert.equal(out.sunoAccountId, null);
  });

  it("conta do item que não existe mais segue a regra normal (1 conta → automática)", () => {
    const out = reuseFromHistory(item("1"), catalog([acc("z")]));
    assert.equal(out.sunoAccountId, "z");
  });

  it("Suno indisponível cai em Local com aviso; sem catálogo fica pendente", () => {
    const out = reuseFromHistory(item("1"), catalog([], false));
    assert.equal(out.provider, "local");
    assert.equal(out.warning, SUNO_REUSE_WARNING);
    const pending = reuseFromHistory(item("1"), null);
    assert.equal(pending.pending, true);
    assert.equal(pending.sunoAccountId, null);
  });

  it("item local sem params usa os campos do item e limites", () => {
    const out = reuseFromHistory(
      {
        id: "x",
        provider: "local",
        prompt: "p",
        lyrics: "l",
        params: {},
        count: 0,
      },
      catalog([]),
    );
    assert.deepEqual(
      [out.provider, out.prompt, out.lyrics, out.duration, out.count],
      ["local", "p", "l", 30, 1],
    );
  });
});

describe("music-history-helpers: fallback da biblioteca local", () => {
  it("agrupa por lote e marca local_file", () => {
    const items = historyFromLibrary([
      {
        ...file("b.mp3"),
        batch: "L1",
        variant: 2,
        prompt: "p",
        requested_duration: 40,
      },
      { ...file("a.mp3"), batch: "L1", variant: 1, prompt: "p", extra: true },
      { ...file("c.mp3"), provider: "local" },
      null,
    ]);
    assert.deepEqual(
      items.map((i) => i.id),
      ["L1", "c.mp3"],
    );
    assert.deepEqual(
      items[0].tracks.map((t) => t.file.file),
      ["a.mp3", "b.mp3"],
    );
    assert.equal(items[0].tracks[0].extra, true);
    assert.equal(items[0].tracks[0].availability, "local_file");
    assert.equal(items[0].count, 2);
    assert.equal(items[1].source, "local");
  });
});

describe("music-history-helpers: erros do Excluir (Anexo A)", () => {
  it("sem conexão: texto próprio, sem atalho", () => {
    const msg = historyDeleteErrorMessage("pia_server_unreachable");
    assert.equal(
      msg.text,
      "Não foi possível excluir agora porque a PIA Server está sem conexão. Tente de novo quando a conexão voltar.",
    );
    assert.equal(msg.route, null);
    assert.notEqual(msg.text, SUNO_TEXT_SERVER_DOWN);
  });

  it("não pareado: texto próprio com atalho para PIA Server", () => {
    const msg = historyDeleteErrorMessage({
      message:
        "Para usar o Suno, entre na PIA Server em Configurações → PIA Server.",
      code: "pia_server_unpaired",
    });
    assert.equal(
      msg.text,
      "Para excluir itens do histórico da conta, entre na PIA Server em Configurações → PIA Server.",
    );
    assert.deepEqual(msg.route, {
      view: "settings",
      section: "Connectors/pia_server",
    });
    assert.deepEqual(msg.route, PIA_SERVER_SETTINGS_ROUTE);
    assert.notEqual(msg.text, SUNO_TEXT_UNPAIRED);
  });

  it("outros codes seguem o mapeamento geral", () => {
    const err = {
      message: "Item do histórico não encontrado.",
      code: "history_item_not_found",
    };
    assert.deepEqual(historyDeleteErrorMessage(err), describeSunoError(err));
    assert.equal(
      historyDeleteErrorMessage(err).text,
      "Item do histórico não encontrado.",
    );
    assert.equal(historyDeleteErrorMessage(null).text, GENERIC_ERROR_TEXT);
    assert.equal(historyDeleteErrorMessage("xyz").text, GENERIC_ERROR_TEXT);
  });

  it("o mapeamento geral (fora do Excluir) não muda", () => {
    assert.equal(
      describeSunoError({ code: "pia_server_unpaired" }).text,
      SUNO_TEXT_UNPAIRED,
    );
  });
});

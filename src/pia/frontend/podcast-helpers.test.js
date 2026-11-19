import test from "node:test";
import assert from "node:assert/strict";
import {
  buildCampaignsList,
  buildParticipantsList,
  buildSettingsDraft,
  campaignsListToObject,
  formatMegabytesHelp,
  formatMinutesHelp,
  normalizeDecimalInput,
  participantsToConfig,
  validateCampaigns,
  validateParticipants,
  validateSettingsDraft,
} from "./podcast-helpers.js";

test("normalizeDecimalInput accepts comma or dot without rounding", () => {
  assert.deepEqual(normalizeDecimalInput("0,005"), {
    ok: true,
    value: 0.005,
    text: "0.005",
  });
  assert.deepEqual(normalizeDecimalInput(" -16.5 "), {
    ok: true,
    value: -16.5,
    text: "-16.5",
  });
  assert.equal(normalizeDecimalInput("abc").ok, false);
});

test("buildParticipantsList preserves people present only in discord_users", () => {
  const list = buildParticipantsList(
    { oouo01: "Dota", dotinha: "Dota" },
    { Dota: "111222", Mestre: "333444" },
  );
  assert.equal(list.length, 2);
  assert.deepEqual(list[0].handles, ["oouo01", "dotinha"]);
  assert.equal(list[0].discordId, "111222");
  assert.equal(list[1].realName, "Mestre");
  assert.deepEqual(list[1].handles, []);
  assert.equal(list[1].discordId, "333444");

  const rebuilt = participantsToConfig(list);
  assert.deepEqual(rebuilt.nomes_reais, { oouo01: "Dota", dotinha: "Dota" });
  assert.deepEqual(rebuilt.discord_users, { Dota: "111222", Mestre: "333444" });
});

test("validateParticipants detects duplicate Discord handle and non-numeric ID", () => {
  const res = validateParticipants([
    { realName: "Dota", handles: ["oouo01"], discordId: "123" },
    { realName: "Caio", handles: ["oouo01"], discordId: "abc" },
  ]);
  assert.equal(res.ok, false);
  assert.equal(
    res.fieldErrors["participant-handles-1"],
    "Este usuário já está ligado a Dota.",
  );
  assert.equal(
    res.fieldErrors["participant-id-1"],
    "O ID do Discord tem só números. Deixe em branco se não quiser menções.",
  );
});

test("campaignsListToObject preserves extra unknown keys", () => {
  const list = buildCampaignsList({
    Dota: {
      Campanha: "Domingos",
      rss_key: "campaigns/Domingos/rss.xml",
      players: { Caio: "Destino" },
      custom_flag: "keep-me",
    },
  });
  const obj = campaignsListToObject(list);
  assert.equal(obj.Dota.custom_flag, "keep-me");
  assert.deepEqual(obj.Dota.players, { Caio: "Destino" });
});

test("validateCampaigns checks rss_key suffix, duplicate folders, and players", () => {
  const res = validateCampaigns([
    {
      narrator: "Dota",
      Campanha: "A",
      rss_key: "campaigns/Shared/rss.xml",
      link: "ftp://invalid",
      playersList: [],
    },
    {
      narrator: "Caio",
      Campanha: "B",
      rss_key: "campaigns/Shared/rss.xml",
      link: "",
      playersList: [{ player: "Dota", character: "" }],
    },
  ]);
  assert.equal(res.ok, false);
  assert.equal(
    res.fieldErrors["campaign-link-0"],
    "Informe um endereço que comece com https:// ou http://.",
  );
  assert.equal(
    res.fieldErrors["campaign-players-0"],
    "Adicione pelo menos um jogador e o personagem dele.",
  );
  assert.equal(
    res.fieldErrors["campaign-rss-1"],
    'Outra campanha já usa a pasta "campaigns/Shared".',
  );
  assert.equal(
    res.fieldErrors["campaign-character-1-0"],
    "Informe o personagem de Dota.",
  );
});

test("validateSettingsDraft validates ranges and formats in PT-BR", () => {
  const draft = buildSettingsDraft({
    app_settings: {
      POLL_INTERVAL_SECONDS: 600,
      DRIVE_PROCESS: false,
      LOCAL_DRIVE_FOLDER: "",
      OWNER_EMAIL: "invalido",
      TRANSCRIPTS_FILE: "transcripts.txt",
      FEED_CACHE_DIR: "data/cache",
    },
    publication: { website: "travelrpg.com", language: "pt_BR" },
    audio: {
      fade_seconds: 0.005,
      compressor_ratio: 0.5,
      compressor_attack_ms: 0,
    },
  });
  const res = validateSettingsDraft(draft);
  assert.equal(res.ok, false);
  assert.equal(
    res.fieldErrors["setting-LOCAL_DRIVE_FOLDER"],
    "Informe uma pasta.",
  );
  assert.equal(
    res.fieldErrors["setting-OWNER_EMAIL"],
    "Informe um e-mail válido, como nome@dominio.com, ou deixe em branco.",
  );
  assert.equal(
    res.fieldErrors["setting-TRANSCRIPTS_FILE"],
    "Informe o nome de um arquivo .html, como transcripts.html.",
  );
  assert.equal(
    res.fieldErrors["setting-publication-website"],
    "Informe um endereço que comece com https:// ou http://.",
  );
  assert.equal(
    res.fieldErrors["setting-publication-language"],
    "Use um código de idioma, como pt-BR.",
  );
  assert.equal(
    res.fieldErrors["setting-audio-compressor_ratio"],
    "A razão do compressor deve ser 1 ou maior.",
  );
  assert.equal(
    res.fieldErrors["setting-audio-compressor_attack_ms"],
    "Informe um tempo maior que zero.",
  );
});

test("format helpers render minutes and megabytes cleanly", () => {
  assert.equal(formatMinutesHelp(600), "= 10 min");
  assert.equal(formatMegabytesHelp(10485760), "≈ 10 MB");
});

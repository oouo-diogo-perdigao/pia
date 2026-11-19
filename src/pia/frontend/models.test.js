import test from "node:test";
import assert from "node:assert/strict";
import {
  PROVIDERS_ORDER,
  STATUS_META,
  normalizeProviderStatus,
  formatProviderQuota,
  formatSessionUsage,
  resolveSelectedModel,
  buildSelectorOptions,
} from "./models.js";

test("PROVIDERS_ORDER and STATUS_META match canonical contract", () => {
  assert.deepEqual(PROVIDERS_ORDER, [
    "codex",
    "agy",
    "openrouter",
    "gemini",
    "groq",
    "cloudflare",
    "local",
  ]);
  assert.equal(STATUS_META.connected.label, "Conectado");
  assert.equal(STATUS_META.login_required.label, "Login necessário");
  assert.equal(STATUS_META.not_installed.label, "Não instalado");
  assert.equal(STATUS_META.error.label, "Erro de autenticação");
  assert.equal(normalizeProviderStatus("connected").color, "green");
  assert.equal(normalizeProviderStatus("unknown").status, "not_installed");
});

test("formatProviderQuota enforces literal fallback and truncates official balance without rounding up", () => {
  const unavailable = formatProviderQuota(
    { quota_status: "unavailable", quota_checked_at: null },
    "codex",
  );
  assert.equal(unavailable.label, "Saldo não informado pelo provedor");
  assert.equal(unavailable.checkedAtText, null);

  const errored = formatProviderQuota(
    { quota_status: "error", quota_checked_at: "2026-11-19T02:20:00Z" },
    "openrouter",
  );
  assert.equal(errored.label, "Saldo não informado pelo provedor");
  assert.match(errored.checkedAtText, /^Verificado às \d{2}:\d{2}$/);

  const localQuota = formatProviderQuota(
    { quota_status: "unavailable" },
    "local",
  );
  assert.equal(
    localQuota.label,
    "Saldo não informado pelo provedor · Execução local (sem cota externa)",
  );

  // 0.079 must truncate to 0,07 (never round up to 0,08)
  const official = formatProviderQuota(
    {
      quota_status: "available",
      quota_remaining: 0.079,
      quota_currency: "USD",
      quota_checked_at: "2026-11-19T02:20:00Z",
    },
    "openrouter",
  );
  assert.equal(official.label, "US$ 0,07 disponíveis");
  assert.match(official.checkedAtText, /^Verificado às \d{2}:\d{2}$/);
});

test("formatSessionUsage formats pt-BR counts, thousands, zero and un-reported tokens", () => {
  assert.equal(
    formatSessionUsage({ requests: 0 }).summary,
    "Nenhuma requisição nesta sessão",
  );
  assert.equal(
    formatSessionUsage({ requests: 0 }, { compact: true }).summary,
    "Sessão: nenhuma requisição",
  );

  const normal = formatSessionUsage({
    requests: 3,
    prompt_tokens: 3000,
    completion_tokens: 1210,
    total_tokens: 4210,
    tokens_reported: true,
  });
  assert.equal(normal.hasUsage, true);
  assert.equal(normal.summary, "3 req · 4.210 tokens");
  assert.equal(normal.detail, "entrada 3.000 · saída 1.210");

  const large = formatSessionUsage(
    {
      requests: 12,
      total_tokens: 128400,
      tokens_reported: true,
    },
    { compact: true },
  );
  assert.equal(large.summary, "Sessão: 12 req · 128,4 mil tokens");

  const noTokens = formatSessionUsage({
    requests: 2,
    tokens_reported: false,
  });
  assert.equal(noTokens.summary, "2 req · tokens não informados pelo provedor");
  assert.equal(
    formatSessionUsage({ requests: 2, tokens_reported: false }, { compact: true })
      .summary,
    "Sessão: 2 req (tokens não informados pelo provedor)",
  );
});

test("resolveSelectedModel and buildSelectorOptions handle Chat, Podcast, automatic and unavailable models", () => {
  const catalog = {
    default_provider: "",
    default_model: "",
    effective_default_label: "gemini-2.5-flash",
    automatic_options: [
      { id: "free", label: "Gratuito (free)" },
      { id: "paid", label: "Pago (paid)" },
    ],
    providers: [
      {
        id: "openrouter",
        name: "OpenRouter",
        auth_type: "api_key",
        status: "login_required",
        models: [{ id: "openai/gpt-4o", label: "GPT-4o" }],
      },
      {
        id: "codex",
        name: "Codex CLI",
        auth_type: "cli",
        status: "connected",
        models: [{ id: "codex", label: "Padrão da conta (Codex CLI)" }],
      },
    ],
  };

  const def = resolveSelectedModel({ provider: "", model: "" }, catalog);
  assert.equal(def.mode, "default");
  assert.equal(def.available, true);
  assert.equal(def.modelLabel, "Padrão da PIA (gemini-2.5-flash)");

  const auto = resolveSelectedModel({ llm_provider: "free", llm_model: "" }, catalog);
  assert.equal(auto.mode, "automatic");
  assert.equal(auto.available, true);
  assert.equal(auto.modelLabel, "Gratuito (free)");

  const disconnected = resolveSelectedModel(
    { llm_provider: "openrouter", llm_model: "openai/gpt-4o" },
    catalog,
  );
  assert.equal(disconnected.available, false);
  assert.equal(disconnected.status, "login_required");
  assert.match(disconnected.blockingReason, /precisa de uma chave/);

  const missingModel = resolveSelectedModel(
    { provider: "codex", model: "inexistente" },
    catalog,
  );
  assert.equal(missingModel.available, false);
  assert.match(missingModel.modelLabel, /Modelo indisponível/);

  const options = buildSelectorOptions(catalog);
  assert.equal(options.defaultOption.label, "Padrão da PIA (gemini-2.5-flash)");
  assert.equal(options.automaticOptions.length, 2);
  assert.deepEqual(
    options.groups.map((g) => g.providerId),
    ["codex", "openrouter"],
  );
});

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  MCP_ACCOUNT_MODES,
  MCP_TRANSPORTS,
  createEmptyAccountDraft,
  createEmptyMcpDraft,
  createEmptySkillDraft,
  draftToMcpPayload,
  draftToSkillPayload,
  filterPlugins,
  filterSkills,
  mcpServerToDraft,
  normalizeMcpServers,
  normalizeMcpTools,
  normalizePlugins,
  normalizeSkills,
  objectToPairs,
  pairsToObject,
  skillToDraft,
  splitCommandArgs,
  validateMcpDraft,
  validateSkillDraft,
} from "./extensions-helpers.js";

describe("extensions-helpers MCP / Plugins / Skills", () => {
  it("exposes STDIO and HTTP com streaming transports and all 3 account modes", () => {
    assert.deepEqual(MCP_TRANSPORTS, [
      { value: "stdio", label: "STDIO" },
      { value: "http", label: "HTTP com streaming" },
    ]);
    assert.deepEqual(
      MCP_ACCOUNT_MODES.map((m) => m.value),
      ["distributed", "incremental", "alternating"],
    );
  });

  it("converts header key/value pairs cleanly in both directions", () => {
    const pairs = [
      { key: "Authorization", value: "Bearer xyz" },
      { key: "", value: "ignored" },
      { key: "X-Org", value: "pia" },
    ];
    assert.deepEqual(pairsToObject(pairs), {
      Authorization: "Bearer xyz",
      "X-Org": "pia",
    });
    assert.deepEqual(objectToPairs({ "X-Org": "pia" }), [
      { key: "X-Org", value: "pia" },
    ]);
    assert.deepEqual(objectToPairs({}), [{ key: "", value: "" }]);
  });

  it("serializes HTTP MCP draft with multi-accounts and OAuth to payload and back", () => {
    const draft = createEmptyMcpDraft();
    draft.name = "Dropbox Corp";
    draft.transport = "http";
    draft.url = "https://mcp.example.com/mcp";
    draft.bearer_token_env = "MCP_BEARER_TOKEN";
    draft.headers = [{ key: "X-Client", value: "pia-ui" }];
    draft.env_headers = [{ key: "X-Api-Key", value: "MY_ENV_KEY" }];
    draft.account_mode = "incremental";
    const acc = createEmptyAccountDraft(1);
    acc.name = "Conta Trabalho";
    acc.context = "Trabalho";
    acc.auth_type = "oauth";
    acc.oauth_client_id = "cid-123";
    acc.oauth_auth_url = "https://auth.example.com/authorize";
    acc.oauth_token_url = "https://auth.example.com/token";
    acc.oauth_scopes = "files.read files.write";
    draft.accounts = [acc];

    const validation = validateMcpDraft(draft);
    assert.equal(validation.valid, true);

    const payload = draftToMcpPayload(draft);
    assert.equal(payload.name, "Dropbox Corp");
    assert.equal(payload.transport, "http_streaming");
    assert.equal(payload.account_mode, "incremental");
    assert.deepEqual(payload.headers, { "X-Client": "pia-ui" });
    assert.deepEqual(payload.env_headers, { "X-Api-Key": "MY_ENV_KEY" });
    assert.equal(payload.accounts.length, 1);
    assert.equal(payload.accounts[0].oauth.scopes, "files.read files.write");

    const roundtrip = mcpServerToDraft(payload);
    assert.equal(roundtrip.name, "Dropbox Corp");
    assert.equal(roundtrip.account_mode, "incremental");
    assert.equal(roundtrip.accounts[0].oauth_scopes, "files.read files.write");
  });

  it("serializes STDIO draft arguments safely and validates invalid inputs", () => {
    assert.deepEqual(splitCommandArgs('-y "@scope/pkg" --root "C:/My Docs"'), [
      "-y",
      "@scope/pkg",
      "--root",
      "C:/My Docs",
    ]);

    const bad = createEmptyMcpDraft();
    bad.transport = "http";
    bad.name = "Broken";
    bad.url = "ftp://invalid";
    assert.equal(validateMcpDraft(bad).valid, false);

    const stdio = createEmptyMcpDraft();
    stdio.name = "Local FS";
    stdio.transport = "stdio";
    stdio.command = "npx";
    stdio.args = "-y @modelcontextprotocol/server-filesystem";
    stdio.env = [{ key: "NODE_ENV", value: "production" }];
    assert.equal(validateMcpDraft(stdio).valid, true);
    const payload = draftToMcpPayload(stdio);
    assert.equal(payload.command, "npx");
    assert.deepEqual(payload.args, [
      "-y",
      "@modelcontextprotocol/server-filesystem",
    ]);
    assert.deepEqual(payload.env, { NODE_ENV: "production" });
  });

  it("normalizes MCP servers, tools, plugins, and filters skills cleanly", () => {
    const servers = normalizeMcpServers({
      servers: [
        {
          id: "suno-1",
          name: "Suno Cluster",
          transport: "streamable_http",
          account_mode: "distributed",
          accounts: [
            { id: "a1", name: "Suno 1", context: "Pessoal" },
            { id: "a2", name: "Suno 2", context: "Trabalho" },
          ],
          tools: [{ name: "generate_song", description: "Creates music" }],
        },
      ],
    });
    assert.equal(servers[0].transport, "http");
    assert.equal(servers[0].tool_count, 1);
    assert.deepEqual(servers[0].available_contexts, ["Pessoal", "Trabalho"]);

    const tools = normalizeMcpTools({
      tools: [{ name: "list_files", description: "Lists remote files" }],
    });
    assert.equal(tools[0].name, "list_files");

    const plugins = normalizePlugins({
      plugins: [
        {
          id: "music",
          name: "Música / Suno",
          description: "Geração musical",
          enabled: true,
          capabilities: ["audio", "suno"],
        },
        {
          id: "podcast",
          name: "Podcast",
          description: "Cortes e roteiro",
          enabled: false,
        },
      ],
    });
    assert.equal(filterPlugins(plugins, "suno").length, 1);

    const skills = normalizeSkills({
      skills: [
        {
          id: "open-notepad",
          name: "Iniciar Bloco de Notas",
          category: "sistema",
          triggers: ["iniciar bloco de notas", "notepad"],
          command: "notepad.exe",
          builtin: true,
        },
        {
          id: "custom-deploy",
          name: "Resumo diário",
          category: "personalizada",
          prompt: "Resuma pendências",
        },
      ],
    });
    assert.equal(filterSkills(skills, { category: "sistema" }).length, 1);
    assert.equal(filterSkills(skills, { query: "notepad" }).length, 1);

    const skillDraft = createEmptySkillDraft();
    skillDraft.name = "Abrir Calculadora";
    skillDraft.description = "Abre a calculadora do Windows";
    skillDraft.trigger = "abrir calc, calculadora";
    skillDraft.command = "calc.exe";
    assert.equal(validateSkillDraft(skillDraft).valid, true);
    const skillPayload = draftToSkillPayload(skillDraft);
    assert.equal(skillPayload.command, "calc.exe");
    assert.deepEqual(skillPayload.triggers, ["abrir calc", "calculadora"]);
    assert.equal(skillToDraft(skillPayload).name, "Abrir Calculadora");
  });
});

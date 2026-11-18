import test from "node:test";
import assert from "node:assert/strict";
import {
  DEFAULT_LEGAL_SERVER,
  legalLinks,
  legalServer,
  legalUrl,
} from "./legal-links.js";

test("usa o servidor padrão quando nada é configurado", () => {
  assert.equal(DEFAULT_LEGAL_SERVER, "https://pia.travelrpg.com");
  for (const server of [undefined, null, "", "   ", 42]) {
    assert.equal(
      legalUrl(server, "privacidade"),
      "https://pia.travelrpg.com/privacidade",
    );
    assert.equal(
      legalUrl(server, "termos"),
      "https://pia.travelrpg.com/termos",
    );
  }
});

test("monta as URLs a partir de um servidor customizado", () => {
  assert.deepEqual(legalLinks("https://pia.exemplo.com.br"), {
    privacidade: "https://pia.exemplo.com.br/privacidade",
    termos: "https://pia.exemplo.com.br/termos",
  });
  assert.equal(
    legalUrl("https://exemplo.com:8443/pia", "termos"),
    "https://exemplo.com:8443/pia/termos",
  );
});

test("remove barra final, query, fragmento e credenciais", () => {
  assert.equal(
    legalUrl("https://pia.exemplo.com/", "termos"),
    "https://pia.exemplo.com/termos",
  );
  assert.equal(
    legalUrl("  https://pia.exemplo.com/base///  ", "privacidade"),
    "https://pia.exemplo.com/base/privacidade",
  );
  assert.equal(
    legalUrl("https://user:senha@pia.exemplo.com/?x=1#connectors", "termos"),
    "https://pia.exemplo.com/termos",
  );
});

test("recusa http e URLs inválidas, caindo no padrão", () => {
  for (const server of [
    "http://pia.exemplo.com",
    "javascript:alert(1)",
    "ftp://pia.exemplo.com",
    "pia.exemplo.com",
    "não é url",
  ]) {
    assert.equal(
      legalUrl(server, "termos"),
      "https://pia.travelrpg.com/termos",
    );
  }
});

test("escolhe o primeiro candidato https válido", () => {
  assert.equal(
    legalServer("http://digitado.local", "https://configurado.com"),
    "https://configurado.com",
  );
  assert.equal(
    legalServer("https://digitado.com/", "https://configurado.com"),
    "https://digitado.com",
  );
  assert.equal(legalServer("", "http://x.com"), DEFAULT_LEGAL_SERVER);
  assert.deepEqual(legalLinks("http://a.com", "https://b.com"), {
    privacidade: "https://b.com/privacidade",
    termos: "https://b.com/termos",
  });
});

test("rejeita páginas desconhecidas", () => {
  assert.throws(() => legalUrl("https://pia.travelrpg.com", "privacy"));
  assert.throws(() => legalUrl("https://pia.travelrpg.com", "../admin"));
});

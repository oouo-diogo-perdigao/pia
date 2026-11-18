import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
const loginCss = read("./login.css");
const workspaceCss = read("./workspace.css");
const serverLogin = read("./ServerLogin.jsx");
const settings = read("./GeneralSettingsTabs.jsx");
const en = JSON.parse(read("../lang/en.json"));
const ptBR = JSON.parse(read("../lang/pt-BR.json"));

function rule(css, selector) {
  const start = css.indexOf(selector + " {");
  assert.ok(start >= 0, "regra ausente: " + selector);
  return css.slice(start, css.indexOf("}", start));
}

test("rodapé legal do login: links sempre sublinhados e foco #b6a2ff", () => {
  assert.match(
    rule(loginCss, ".pia-legal-footer a"),
    /text-decoration: underline/,
  );
  for (const state of [":hover", ":visited", ":focus-visible"]) {
    const block = loginCss.includes(".pia-legal-footer a" + state + " {")
      ? rule(loginCss, ".pia-legal-footer a" + state)
      : "";
    assert.doesNotMatch(block, /text-decoration:\s*none/, state);
  }
  assert.match(
    rule(loginCss, ".pia-legal-footer a:focus-visible"),
    /outline: 2px solid #b6a2ff/,
  );
});

test("ServerLogin: texto do RF05, links externos com aviso para leitor de tela", () => {
  const footer = serverLogin.slice(
    serverLogin.indexOf('<p className="pia-legal-footer">'),
  );
  assert.match(footer, /Ao continuar, você concorda com os/);
  assert.match(footer, /e declara ter lido a/);
  const links = [...footer.matchAll(/<a\s[^>]*>/g)].slice(0, 2);
  assert.equal(links.length, 2);
  for (const [link] of links) {
    assert.match(link, /target="_blank"/);
    assert.match(link, /rel="noreferrer"/);
  }
  assert.equal(
    (
      footer.match(
        /<span className="sr-only"> \(abre no navegador\)<\/span>/g,
      ) || []
    ).length,
    2,
  );
  assert.doesNotMatch(serverLogin, /<Anchor[^>]*legal/);
});

test("card Sobre e legal: foco #b6a2ff, sem Última atualização e traduzido", () => {
  assert.match(
    rule(workspaceCss, ".settings-card .legal-settings-action:focus-visible"),
    /outline: 2px solid #b6a2ff/,
  );
  assert.match(settings, /className="legal-settings-action"/);
  assert.match(settings, /aria-labelledby="sobre-legal-t"/);
  assert.doesNotMatch(settings, /Última atualização/);
  const card = settings.slice(
    settings.indexOf("const LEGAL_ROWS"),
    settings.indexOf("export default function GeneralSettingsTabs"),
  );
  const keys = [
    ...card.matchAll(/t\("([^"]+)"\)/g),
    ...card.matchAll(/(?:title|description):\s*"([^"]+)"/g),
  ].map((match) => match[1]);
  assert.ok(keys.length >= 6);
  for (const key of keys) {
    assert.equal(ptBR[key], key, "pt-BR: " + key);
    assert.ok(en[key] && en[key] !== key, "en: " + key);
  }
});

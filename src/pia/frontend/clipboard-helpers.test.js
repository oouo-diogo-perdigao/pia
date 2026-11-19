import test from "node:test";
import assert from "node:assert/strict";
import {
  copyWithExecCommand,
  copyTextWithFallback,
} from "./clipboard-helpers.js";

function createFakeDocument({ execResult = true, execThrows = false } = {}) {
  const appended = [];
  const removed = [];
  let createdElement = null;
  let selected = false;
  let execCommandCalled = null;

  const doc = {
    activeElement: null,
    body: {
      appendChild(el) {
        appended.push(el);
      },
      removeChild(el) {
        removed.push(el);
      },
    },
    createElement(tag) {
      assert.equal(tag, "textarea");
      createdElement = {
        value: "",
        style: {},
        attrs: {},
        setAttribute(k, v) {
          this.attrs[k] = v;
        },
        focus() {},
        select() {
          selected = true;
        },
        setSelectionRange() {},
        remove() {
          removed.push(this);
        },
      };
      return createdElement;
    },
    execCommand(cmd) {
      execCommandCalled = cmd;
      if (execThrows) throw new Error("execCommand blocked");
      return execResult;
    },
    getState() {
      return { appended, removed, createdElement, selected, execCommandCalled };
    },
  };
  return doc;
}

test("copyTextWithFallback uses navigator.clipboard.writeText when available", async () => {
  const copied = [];
  const doc = createFakeDocument();
  const ok = await copyTextWithFallback("erro 123", {
    nav: {
      clipboard: {
        async writeText(val) {
          copied.push(val);
        },
      },
    },
    doc,
  });
  assert.equal(ok, true);
  assert.deepEqual(copied, ["erro 123"]);
  assert.equal(doc.getState().appended.length, 0);
});

test("copyTextWithFallback falls back to fixed opacity-0 textarea + execCommand('copy') when clipboard.writeText rejects (HTTP localhost / permission denied)", async () => {
  const doc = createFakeDocument({ execResult: true });
  let nativeCalled = false;
  const ok = await copyTextWithFallback("Falha de conexão HTTP", {
    nav: {
      clipboard: {
        async writeText() {
          throw new DOMException("Write permission denied", "NotAllowedError");
        },
      },
    },
    doc,
    nativeCopy: async () => {
      nativeCalled = true;
    },
  });
  assert.equal(ok, true);
  assert.equal(nativeCalled, false);
  const state = doc.getState();
  assert.equal(state.appended.length, 1);
  assert.equal(state.removed.length, 1);
  assert.equal(state.createdElement.value, "Falha de conexão HTTP");
  assert.equal(state.createdElement.style.position, "fixed");
  assert.equal(state.createdElement.style.opacity, "0");
  assert.equal(state.selected, true);
  assert.equal(state.execCommandCalled, "copy");
});

test("copyTextWithFallback falls back to textarea when navigator.clipboard is undefined (plain HTTP)", async () => {
  const doc = createFakeDocument({ execResult: true });
  const ok = await copyTextWithFallback("Erro HTTP LAN", {
    nav: {},
    doc,
  });
  assert.equal(ok, true);
  assert.equal(doc.getState().execCommandCalled, "copy");
  assert.equal(doc.getState().createdElement.value, "Erro HTTP LAN");
});

test("copyTextWithFallback falls back to nativeCopy when execCommand fails, and throws when all fail", async () => {
  const nativeCopied = [];
  const ok = await copyTextWithFallback("desktop fallback", {
    nav: {},
    doc: createFakeDocument({ execResult: false }),
    nativeCopy: async (text) => {
      nativeCopied.push(text);
    },
  });
  assert.equal(ok, true);
  assert.deepEqual(nativeCopied, ["desktop fallback"]);

  await assert.rejects(
    () =>
      copyTextWithFallback("will fail", {
        nav: {},
        doc: createFakeDocument({ execThrows: true }),
        nativeCopy: async () => {
          throw new Error("no native bridge");
        },
      }),
    /Não foi possível copiar/,
  );
});

test("copyWithExecCommand cleans up textarea even when execCommand throws", () => {
  const doc = createFakeDocument({ execThrows: true });
  const ok = copyWithExecCommand("boom", doc);
  assert.equal(ok, false);
  assert.equal(doc.getState().appended.length, 1);
  assert.equal(doc.getState().removed.length, 1);
});

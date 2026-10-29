import test from "node:test";
import assert from "node:assert/strict";
import { fingerprint, formatTime } from "./forms.js";
test("dirty state ignores key order but notices typed values and reverted edits", () => {
  const saved = fingerprint({
    accounts: ["work"],
    enabled: false,
    nested: { a: 1, b: 2 },
  });
  assert.equal(
    saved,
    fingerprint({ nested: { b: 2, a: 1 }, enabled: false, accounts: ["work"] }),
  );
  assert.notEqual(
    saved,
    fingerprint({ accounts: ["work"], enabled: true, nested: { a: 1, b: 2 } }),
  );
  assert.notEqual(fingerprint({ value: 0 }), fingerprint({ value: "0" }));
  assert.notEqual(fingerprint({ value: "" }), fingerprint({ value: false }));
});
test("audio durations use readable hours minutes and seconds including long sessions", () => {
  assert.equal(formatTime(123), "00:02:03");
  assert.equal(formatTime(333), "00:05:33");
  assert.equal(formatTime(21504.9), "05:58:24");
  assert.equal(formatTime(null), "00:00:00");
  assert.equal(formatTime(-10), "00:00:00");
});

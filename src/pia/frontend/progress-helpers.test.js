import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  FINAL_PROGRESS_STATES,
  isFinalProgressState,
  progressColor,
} from "./progress-helpers.js";

describe("progress-helpers", () => {
  it("trata completed, error e interrupted como estados finais", () => {
    for (const state of ["completed", "error", "interrupted"])
      assert.equal(isFinalProgressState(state), true, state);
    assert.deepEqual(FINAL_PROGRESS_STATES, [
      "completed",
      "error",
      "interrupted",
    ]);
  });

  it("mantém animação em estados em andamento ou ausentes", () => {
    for (const state of [
      "running",
      "queued",
      "",
      undefined,
      null,
      "Interrupted",
    ])
      assert.equal(isFinalProgressState(state), false, String(state));
  });

  it("usa vermelho no erro, amarelo na interrupção e violeta no resto", () => {
    assert.equal(progressColor("error"), "red");
    assert.equal(progressColor("interrupted"), "yellow");
    assert.equal(progressColor("completed"), "violet");
    assert.equal(progressColor("running"), "violet");
    assert.equal(progressColor(undefined), "violet");
  });
});

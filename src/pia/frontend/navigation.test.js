import test from "node:test";
import assert from "node:assert/strict";
import { ScreenHistory } from "./navigation.js";
test("history caps at 50 snapshots and never executes actions", () => {
  const history = new ScreenHistory();
  let actions = 0;
  for (let i = 0; i < 70; i++)
    history.push({
      view: "app",
      app: "podcast_automation",
      sub: i % 2 ? "campaigns" : "principal",
      i,
    });
  assert.equal(history.entries.length, 50);
  assert.equal(history.entries[0].route.i, 20);
  const entry = history.select(history.entries[0].key);
  assert.equal(entry.route.i, 20);
  assert.equal(actions, 0);
  history.push({ view: "chat", chat: "existing" });
  assert.equal(history.entries.length, 2);
  assert.equal(actions, 0);
});
test("snapshots do not share mutable objects with callers", () => {
  const history = new ScreenHistory(),
    route = { view: "app", values: { account: "one" } };
  const entry = history.push(route);
  route.values.account = "two";
  assert.equal(entry.route.values.account, "one");
});

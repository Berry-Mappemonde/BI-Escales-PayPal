import test from "node:test";
import assert from "node:assert/strict";
import { unmountRootLater } from "./unmountRootLater.js";

test("unmountRootLater ne démonte pas de façon synchrone", () => {
  let calls = 0;
  const queue = [];
  unmountRootLater({ unmount: () => { calls += 1; } }, (fn) => queue.push(fn));
  assert.equal(calls, 0);
  queue.forEach((fn) => fn());
  assert.equal(calls, 1);
});

test("unmountRootLater tolère une racine absente ou qui lève", () => {
  unmountRootLater(null);
  const queue = [];
  unmountRootLater({ unmount: () => { throw new Error("x"); } }, (fn) => queue.push(fn));
  assert.doesNotThrow(() => queue.forEach((fn) => fn()));
});

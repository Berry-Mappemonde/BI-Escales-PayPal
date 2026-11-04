import { describe, it, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import {
  ADMIN_HEADER,
  ADMIN_STORAGE_KEY,
  adminHeaders,
  captureAdminSecretFromUrl,
  getAdminSecret,
  hasAdminSecret,
  setAdminSecret,
} from "./adminSecret.js";

function fakeStorage() {
  const m = new Map();
  return {
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => m.set(k, String(v)),
    removeItem: (k) => m.delete(k),
  };
}

describe("adminSecret", () => {
  let saved;
  beforeEach(() => {
    saved = globalThis.window;
    globalThis.window = { localStorage: fakeStorage() };
  });
  afterEach(() => {
    globalThis.window = saved;
  });

  it("visitor has no key and sends no header", () => {
    assert.equal(getAdminSecret(), "");
    assert.equal(hasAdminSecret(), false);
    assert.deepEqual(adminHeaders(), {});
  });

  it("stores, trims and clears the key", () => {
    setAdminSecret("  s3cret  ");
    assert.equal(getAdminSecret(), "s3cret");
    assert.deepEqual(adminHeaders(), { [ADMIN_HEADER]: "s3cret" });
    assert.equal(globalThis.window.localStorage.getItem(ADMIN_STORAGE_KEY), "s3cret");
    setAdminSecret("");
    assert.equal(hasAdminSecret(), false);
  });

  it("captures ?admin= from the URL and strips it from the address bar", () => {
    const calls = [];
    const win = {
      localStorage: globalThis.window.localStorage,
      location: { href: "https://naviguide.fr/?admin=abc123&lang=fr#map" },
      history: { state: null, replaceState: (...a) => calls.push(a) },
    };
    assert.equal(captureAdminSecretFromUrl(win), true);
    assert.equal(getAdminSecret(), "abc123");
    assert.equal(calls.length, 1);
    assert.equal(calls[0][2], "/?lang=fr#map");
  });

  it("does nothing without the parameter", () => {
    const win = {
      localStorage: globalThis.window.localStorage,
      location: { href: "https://naviguide.fr/?lang=fr" },
      history: { state: null, replaceState: () => { throw new Error("must not be called"); } },
    };
    assert.equal(captureAdminSecretFromUrl(win), false);
    assert.equal(getAdminSecret(), "");
  });
});

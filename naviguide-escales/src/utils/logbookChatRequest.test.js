import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { chatErrorKey, LOGBOOK_CHAT_TIMEOUT_MS, postLogbookChat } from "./logbookChatRequest.js";
import fr from "../i18n/fr.js";
import en from "../i18n/en.js";

const response = (status, payload) => ({ ok: status >= 200 && status < 300, status, json: async () => payload });

describe("postLogbookChat", () => {
  it("exports the default timeout and parses successful JSON", async () => {
    assert.equal(LOGBOOK_CHAT_TIMEOUT_MS, 45000);
    assert.deepEqual(await postLogbookChat({ url: "/chat", body: {}, fetchImpl: async () => response(200, { answer: "ahoy" }) }), { answer: "ahoy" });
  });

  it("clears the timer after success", async () => {
    const originalSetTimeout = globalThis.setTimeout;
    const originalClearTimeout = globalThis.clearTimeout;
    let cleared;
    globalThis.setTimeout = () => 123;
    globalThis.clearTimeout = (id) => { cleared = id; };
    try {
      await postLogbookChat({ url: "/chat", body: {}, fetchImpl: async () => response(200, {}) });
      assert.equal(cleared, 123);
    } finally {
      globalThis.setTimeout = originalSetTimeout;
      globalThis.clearTimeout = originalClearTimeout;
    }
  });

  it("classifies timeout when fetch honors the abort signal", async () => {
    await assert.rejects(postLogbookChat({ url: "/chat", body: {}, timeoutMs: 5, fetchImpl: (_url, { signal }) => new Promise((_resolve, reject) => signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")))) }), { code: "timeout" });
  });

  it("classifies timeout while reading a slow successful response body", async () => {
    await assert.rejects(postLogbookChat({ url: "/chat", body: {}, timeoutMs: 5, fetchImpl: (_url, { signal }) => Promise.resolve({ ok: true, json: () => new Promise((_resolve, reject) => signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")))) }) }), { code: "timeout" });
  });

  it("enforces the timeout when an injected fetch ignores abort", async () => {
    await assert.rejects(postLogbookChat({ url: "/chat", body: {}, timeoutMs: 5, fetchImpl: () => new Promise(() => {}) }), { code: "timeout" });
  });

  it("does not return a successful body after caller cancellation", async () => {
    const controller = new AbortController();
    await assert.rejects(postLogbookChat({
      url: "/chat", body: {}, signal: controller.signal,
      fetchImpl: async () => ({ ok: true, json: async () => { controller.abort(); return { answer: "late" }; } }),
    }), { code: "aborted" });
  });

  it("classifies caller cancellation", async () => {
    const controller = new AbortController();
    const request = postLogbookChat({ url: "/chat", body: {}, signal: controller.signal, fetchImpl: (_url, { signal }) => new Promise((_resolve, reject) => signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")))) });
    controller.abort();
    await assert.rejects(request, { code: "aborted" });
  });

  it("rejects promptly on external abort when fetch ignores abort", async () => {
    const controller = new AbortController();
    const started = Date.now();
    const request = postLogbookChat({
      url: "/chat", body: {}, signal: controller.signal, timeoutMs: 5000,
      fetchImpl: () => new Promise(() => {}),
    });
    controller.abort();
    await assert.rejects(request, { code: "aborted" });
    assert.ok(Date.now() - started < 500, "external abort should win without waiting for the 5 s timeout");
  });

  it("classifies network failures", async () => {
    await assert.rejects(postLogbookChat({ url: "/chat", body: {}, fetchImpl: async () => { throw new TypeError("Failed to fetch"); } }), { code: "network" });
  });

  it("classifies HTTP errors and preserves detail and status", async () => {
    await assert.rejects(postLogbookChat({ url: "/chat", body: {}, fetchImpl: async () => response(413, { detail: "large" }) }), { code: "tooLong", status: 413, detail: "large" });
    await assert.rejects(postLogbookChat({ url: "/chat", body: {}, fetchImpl: async () => response(400, { detail: "question vide" }) }), { code: "empty", status: 400, detail: "question vide" });
    await assert.rejects(postLogbookChat({ url: "/chat", body: {}, fetchImpl: async () => response(500, { detail: "oops" }) }), { code: "server", status: 500, detail: "oops" });
  });
});

describe("chatErrorKey", () => {
  it("maps known and unknown error codes", () => {
    assert.deepEqual(["timeout", "network", "empty", "tooLong", "server"].map(chatErrorKey), ["chatErrTimeout", "chatErrNetwork", "chatErrEmpty", "chatErrTooLong", "chatErrServer"]);
    assert.equal(chatErrorKey("other"), "chatErrServer");
  });

  it("has all chat error translations in French and English", () => {
    for (const key of ["chatErrTimeout", "chatErrNetwork", "chatErrEmpty", "chatErrTooLong", "chatErrServer"]) {
      assert.ok(fr[key], `missing fr.${key}`);
      assert.ok(en[key], `missing en.${key}`);
    }
  });
});

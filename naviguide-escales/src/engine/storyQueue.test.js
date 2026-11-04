import { describe, it, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  KEEP_STORY_TYPES,
  MAX_STORY_PENDING,
  enqueueStory,
  pendingStoryCount,
  resetStoryQueue,
  shouldEnqueueStory,
  storyPayload,
  subscribeStories,
} from "./storyQueue.js";

const src = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "storyQueue.js"), "utf8");

function waitJob(eventId, status, ms = 400) {
  return new Promise((resolve, reject) => {
    const t = setTimeout(() => reject(new Error(`timeout waiting ${status}`)), ms);
    const off = subscribeStories((job) => {
      if (job.eventId === eventId && job.status === status) {
        clearTimeout(t);
        off();
        resolve(job);
      }
    });
  });
}

describe("storyQueue contract", () => {
  it("is the usual cascade, not Nemotron / Tavily / Token Factory", () => {
    assert.match(src, /nim-or-claude/);
    assert.match(src, /void runStory/);
    assert.match(src, /Play never awaits/);
    assert.match(src, /Not Nemotron/);
    assert.match(src, /Not Token Factory/);
    assert.doesNotMatch(src, /tavily\.search|nvidia-nemotron/);
  });
});

describe("shouldEnqueueStory + payload", () => {
  it("Brut: never enqueues, whatever the judge", () => {
    const now = { judge: "now", story: { status: "template" } };
    assert.equal(shouldEnqueueStory(now), false);
    assert.equal(shouldEnqueueStory(now, { written: false }), false);
    assert.equal(shouldEnqueueStory({ judge: "group", story: { status: "template" } }, { written: true }), false);
    assert.equal(shouldEnqueueStory({ judge: "later", story: { status: "template" } }, { written: true }), false);
    assert.equal(shouldEnqueueStory({ judge: "hide" }, { written: true }), false);
  });

  it("Rédigé: one now event, skips pending/ready/group", () => {
    assert.equal(shouldEnqueueStory({ judge: "now", story: { status: "template" } }, { written: true }), true);
    assert.equal(shouldEnqueueStory({ judge: "now", story: { status: "pending" } }, { written: true }), false);
    assert.equal(shouldEnqueueStory({ judge: "now", story: { status: "ready" } }, { written: true }), false);
  });

  it("asks for :online only when a pack URL + gold/alert/click", () => {
    const gold = storyPayload({
      id: "zee-enter:1",
      type: "zee-enter",
      severity: "watch",
      judge: "now",
      payload: {
        zee: { gold_pack: true },
        poe: { url: "https://douane.gouv.fr", name: "La Rochelle" },
        tavily: null,
      },
    });
    assert.equal(gold.needPage, true);
    assert.equal(gold.pageUrl, "https://douane.gouv.fr");
    assert.equal(gold.tavily, null);

    const plain = storyPayload({
      id: "wind-shift:1",
      type: "wind-shift",
      severity: "info",
      judge: "now",
      payload: { kind: "forecast", tavily: null },
    });
    assert.equal(plain.needPage, false);
    assert.equal(plain.pageUrl, null);
  });

  it("adds the skipper block: the orders that made THIS event switch, one value per id", () => {
    const body = storyPayload({
      id: "hs-shift:forecast:3",
      stableKey: "hs-shift:forecast",
      type: "hs-shift",
      kind: "climatology",
      severity: "alert",
      judge: "now",
      payload: { hs: 3.6, p50: 3.6, p90: 4.8, kind: "climatology", alert: true, tavily: null, nvidia: null },
      skipper: {
        profile: "cruise",
        profile_phrase: "Ordres Berry — croisière.",
        comfort: "normal",
        boat: { name: "Leopard 46", loaM: 14, draftM: 1.4 },
        used: [
          { id: "hsShiftM", value: 1, unit: "m", source: "usage", rule: "variation de houle (croisière)" },
          { id: "hsAlertM", value: 3.5, unit: "m", source: "usage", rule: "constante Croisière E1 3,5 m" },
          { id: "hsAlertM", value: 99, unit: "m", source: "usage", rule: "duplicate must be dropped" },
        ],
      },
    });
    assert.equal(body.event, "hs-shift");
    assert.equal(body.kind, "climatology");
    assert.equal(body.skipper.profile, "cruise");
    assert.equal(body.skipper.profile_phrase, "Ordres Berry — croisière.");
    assert.equal(body.skipper.comfort, "normal");
    assert.deepEqual(body.skipper.boat, { name: "Leopard 46", loaM: 14, draftM: 1.4 });
    assert.deepEqual(body.skipper.used.map((u) => u.id), ["hsShiftM", "hsAlertM"]);
    assert.deepEqual(
      body.skipper.used[1],
      { id: "hsAlertM", value: 3.5, unit: "m", source: "usage", rule: "constante Croisière E1 3,5 m" },
    );
    assert.equal(body.payload.p90, 4.8, "the orders never fill or change a weather field");
    assert.equal(body.tavily, null);
    assert.equal(body.nvidia, null);
    assert.ok(!JSON.stringify(body).includes("polarRaw"));
  });

  it("keeps skipper null when the event carries no orders", () => {
    const body = storyPayload({ id: "zee-exit:1", type: "zee-exit", judge: "now", payload: { tavily: null } });
    assert.equal(body.skipper, null);
    assert.equal(body.tavily, null);
  });
});

describe("enqueueStory fire-and-forget", () => {
  const origFetch = globalThis.fetch;

  beforeEach(() => {
    resetStoryQueue();
    globalThis.fetch = async () => new Response(JSON.stringify({
      status: "ready",
      text: "On vient d’entrer dans la ZEE espagnole. Ports d’entrée : Palma.",
      engine: "nvidia-gpt-oss-20b",
      cascade: "nim-or-claude",
      tavily: null,
      nvidia: "nvidia-gpt-oss-20b",
    }), { status: 200, headers: { "Content-Type": "application/json" } });
  });

  afterEach(() => {
    globalThis.fetch = origFetch;
    resetStoryQueue();
  });

  it("returns pending immediately and becomes ready without blocking", async () => {
    const first = enqueueStory({
      event: "zee-enter",
      eventId: "zee-enter:1",
      tavily: null,
      nvidia: null,
    });
    assert.equal(first.status, "pending");
    assert.equal(first.cascade, "nim-or-claude");
    assert.equal(first.tavily, null);
    assert.equal(first.nvidia, null);
    const ready = await waitJob("zee-enter:1", "ready");
    assert.match(ready.text, /ZEE/);
    assert.equal(ready.tavily, null);
    assert.equal(ready.nvidia, "nvidia-gpt-oss-20b");
  });

  it("Rédigé: one fetch per now event and only once; Brut: none", async () => {
    const urls = [];
    globalThis.fetch = async (url) => {
      urls.push(String(url));
      return new Response(JSON.stringify({
        status: "ready",
        text: "Entrée dans les eaux espagnoles.",
        engine: "nemotron-super",
      }), { status: 200, headers: { "Content-Type": "application/json" } });
    };
    const nowA = { judge: "now", id: "now-a", type: "zee-enter", story: { status: "template" } };
    const nowB = { judge: "now", id: "now-b", type: "amp-enter", story: { status: "template" } };
    const group = { judge: "group", id: "grp", type: "zee-enter", story: { status: "template" } };
    const later = { judge: "later", id: "lat", type: "zee-ahead", story: { status: "template" } };
    for (const ev of [nowA, nowB, group, later]) {
      if (shouldEnqueueStory(ev, { written: false })) {
        enqueueStory({ event: ev.type, eventId: ev.id, type: ev.type });
      }
    }
    assert.equal(urls.length, 0);
    const waiting = Promise.all([
      waitJob("now-a", "ready", 2000),
      waitJob("now-b", "ready", 2000),
    ]);
    for (const ev of [nowA, nowB, group, later]) {
      if (shouldEnqueueStory(ev, { written: true })) {
        enqueueStory({ event: ev.type, eventId: ev.id, type: ev.type });
      }
    }
    await waiting;
    assert.equal(urls.filter((u) => u.includes("/ici/story")).length, 2);
    const n = urls.length;
    nowA.story = { status: "ready" };
    nowB.story = { status: "ready" };
    for (const ev of [nowA, nowB, group, later]) {
      if (shouldEnqueueStory(ev, { written: true })) {
        enqueueStory({ event: ev.type, eventId: ev.id, type: ev.type });
      }
    }
    assert.equal(urls.length, n);
  });

  it("does not open a fourth later job when three are pending", () => {
    globalThis.fetch = (_url, opts) => new Promise((_, reject) => {
      opts?.signal?.addEventListener("abort", () => {
        const err = new Error("aborted");
        err.name = "AbortError";
        reject(err);
      });
    });
    enqueueStory({ event: "zee-ahead", eventId: "a", type: "zee-ahead" });
    enqueueStory({ event: "amp-ahead", eventId: "b", type: "amp-ahead" });
    enqueueStory({ event: "poe-ahead", eventId: "c", type: "poe-ahead" });
    const fourth = enqueueStory({ event: "wind-shift", eventId: "d", type: "wind-shift" });
    assert.equal(fourth.status, "pending");
    assert.ok(pendingStoryCount() <= MAX_STORY_PENDING);
    const marina = enqueueStory({ event: "marina-refuge", eventId: "e", type: "marina-refuge" });
    assert.equal(marina.status, "pending");
    assert.ok(pendingStoryCount() <= MAX_STORY_PENDING);
    assert.ok(KEEP_STORY_TYPES.includes("marina-refuge"));
  });
});

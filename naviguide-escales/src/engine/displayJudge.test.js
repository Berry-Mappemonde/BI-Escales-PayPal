import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  JUDGE_GROUP,
  JUDGE_HIDE,
  JUDGE_LATER,
  JUDGE_NOW,
  judgeEvent,
  judgeEvents,
} from "./displayJudge.js";
import { resolveOrders } from "./skipperOrders.js";

const src = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "displayJudge.js"), "utf8");

function ev(type, extra = {}) {
  return {
    id: extra.id || `${type}:1`,
    type,
    severity: extra.severity || "info",
    whenNm: extra.whenNm ?? 0,
    filmCum: extra.filmCum ?? 0,
    payload: extra.payload || { tavily: null, nvidia: null },
    story: { status: "template" },
  };
}

describe("displayJudge", () => {
  it("is a rules judge, not Ultra / Nemotron", () => {
    assert.match(src, /Not Nemotron Ultra/);
    assert.doesNotMatch(src, /Token Factory|Tavily\.|fetch\(/);
  });

  it("zee-enter → now", () => {
    const r = judgeEvent(ev("zee-enter"));
    assert.equal(r.judge, JUDGE_NOW);
  });

  it("wind-shift → later unless chained to gale", () => {
    assert.equal(judgeEvent(ev("wind-shift")).judge, JUDGE_LATER);
    assert.equal(
      judgeEvent(ev("wind-shift", { payload: { chainedGale: true } })).judge,
      JUDGE_NOW,
    );
  });

  it("wind-gale and marina-refuge stay now and never group", () => {
    const { judged, briefing } = judgeEvents([
      ev("wind-gale", { severity: "alert" }),
      ev("marina-refuge", { severity: "alert", id: "marina-refuge:Minimes" }),
      ev("wind-shift", { id: "wind-shift:2" }),
    ]);
    const gale = judged.find((e) => e.type === "wind-gale");
    const marina = judged.find((e) => e.type === "marina-refuge");
    assert.equal(gale.judge, JUDGE_NOW);
    assert.equal(marina.judge, JUDGE_NOW);
    assert.equal(briefing.type, "marina-refuge");
    assert.ok(!judged.some((e) => e.type === "group"));
  });

  it("cinema hides chatty science / AtoN / projects", () => {
    assert.equal(judgeEvent(ev("science-hit"), { cinema: true }).judge, JUDGE_HIDE);
    assert.equal(judgeEvent(ev("aton-nearby"), { cinema: true }).judge, JUDGE_HIDE);
    assert.equal(judgeEvent(ev("science-hit"), { cinema: false }).judge, JUDGE_LATER);
  });

  it("review-admin and grib-absent stay hidden", () => {
    assert.equal(judgeEvent(ev("review-admin")).judge, JUDGE_HIDE);
    assert.equal(judgeEvent(ev("grib-absent")).judgeReason, "grib-hud");
  });

  it("skipper click forces now on a later event", () => {
    const evn = ev("wind-shift", { id: "wind-shift:click" });
    const r = judgeEvent(evn, { skipperClickId: "wind-shift:click" });
    assert.equal(r.judge, JUDGE_NOW);
    assert.equal(r.judgeReason, "skipper-click");
    const keyed = { ...ev("zee-ahead"), stableKey: "zee-ahead:8462" };
    const viaKey = judgeEvent(keyed, { skipperClickId: "zee-ahead:8462" });
    assert.equal(viaKey.judge, JUDGE_NOW);
  });

  it("ahead events stay later until the playhead or a click", () => {
    assert.equal(judgeEvent(ev("zee-ahead", { whenNm: 40 })).judge, JUDGE_LATER);
    assert.equal(judgeEvent(ev("amp-ahead", { whenNm: 40 })).judge, JUDGE_LATER);
    assert.equal(judgeEvent(ev("poe-ahead", { whenNm: 40 })).judge, JUDGE_LATER);
  });

  it("groups zee-enter + amp-enter into one digest", () => {
    const { judged, briefing, digest } = judgeEvents([
      ev("zee-enter", { id: "zee-enter:5677" }),
      ev("amp-enter", { id: "amp-enter:ps-1", payload: { visitable: true } }),
    ]);
    assert.ok(judged.some((e) => e.judge === JUDGE_GROUP));
    assert.equal(digest.type, "group");
    assert.equal(briefing.type, "group");
    assert.deepEqual(digest.payload.members, ["zee-enter", "amp-enter"]);
    assert.equal(digest.payload.tavily, null);
    assert.equal(digest.payload.nvidia, null);
  });

  it("fast profile groups two later meteo events into one digest", () => {
    const { judged, digest } = judgeEvents([
      ev("wind-shift", { id: "w1", whenNm: 0 }),
      ev("current-shift", { id: "c1", whenNm: 20 }),
    ], { profile: "fast" });
    assert.equal(digest.type, "group");
    assert.ok(judged.filter((e) => e.judge === JUDGE_GROUP).length >= 2);
  });

  it("hides a duplicate id already seen", () => {
    const r = judgeEvent(ev("zee-enter", { id: "zee-enter:5677:1" }), {
      seenIds: ["zee-enter:5677:1"],
    });
    assert.equal(r.judge, JUDGE_HIDE);
    assert.equal(r.judgeReason, "duplicate");
  });

  it("amp-enter without visit_url stays later", () => {
    const r = judgeEvent(ev("amp-enter", { payload: { visitable: false } }));
    assert.equal(r.judge, JUDGE_LATER);
  });

  it("severe wx-alert is now and does not get swallowed by a digest", () => {
    const { judged, briefing } = judgeEvents([
      ev("wx-alert", { payload: { rain: true, severe: true }, severity: "alert" }),
      ev("wind-shift", { id: "w2" }),
      ev("current-shift", { id: "c2" }),
    ]);
    const wx = judged.find((e) => e.type === "wx-alert");
    assert.equal(wx.judge, JUDGE_NOW);
    assert.equal(briefing.type, "wx-alert");
  });

  it("reads Hs alert and grouping window from the skipper orders", () => {
    const coastal = resolveOrders({ profile: "coastal" });
    const ocean = resolveOrders({ profile: "ocean" });
    const sea = () => ev("hs-shift", { payload: { hs: 2.7, alert: false } });
    assert.equal(judgeEvent(sea()).judge, JUDGE_LATER, "cruise default: 2.7 m is under 3.5 m");
    assert.equal(judgeEvent(sea(), { orders: coastal }).judge, JUDGE_NOW, "coastal speaks at 2.5 m");
    assert.equal(judgeEvent(sea(), { orders: ocean }).judge, JUDGE_LATER);

    const wx = () => ev("wx-alert", { payload: { hs: 3.8, severe: false, rain: false, gale: false } });
    assert.equal(judgeEvent(wx()).judge, JUDGE_NOW, "cruise: 3.8 m ≥ 3.5 m");
    assert.equal(judgeEvent(wx(), { orders: ocean }).judge, JUDGE_LATER, "ocean: 3.8 m < 5.0 m");

    const pair = [ev("wind-shift", { id: "w1", whenNm: 0 }), ev("current-shift", { id: "c1", whenNm: 12 })];
    assert.ok(judgeEvents(pair).judged.some((e) => e.judge === JUDGE_GROUP), "cruise groups inside 15 nm");
    assert.ok(
      !judgeEvents(pair, { orders: coastal }).judged.some((e) => e.judge === JUDGE_GROUP),
      "coastal window is 8 nm: denser, separate pills",
    );
  });
});

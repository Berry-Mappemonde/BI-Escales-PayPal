import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { catamaranSvg, catamaranTransform } from "./catamaranIcon.js";

describe("catamaranTransform", () => {
  it("stays upright (no scaleX/scaleY) regardless of heading", () => {
    for (const b of [0, 90, 180, 270, 45]) {
      const t = catamaranTransform(b);
      assert.equal(t.includes("scaleX"), false);
      assert.equal(t.includes("scaleY"), false);
      assert.ok(t.includes("rotate"));
    }
  });

  it("points the bow with the heading (proue = nord SVG)", () => {
    assert.equal(catamaranTransform(0), "rotate(0deg)");
    assert.equal(catamaranTransform(90), "rotate(90deg)");
    assert.equal(catamaranTransform(180), "rotate(180deg)");
    assert.equal(catamaranTransform(270), "rotate(270deg)");
    assert.equal(catamaranTransform(-90), "rotate(270deg)");
  });
});

describe("catamaranSvg", () => {
  it("marks bow-north and exposes the CSS-rotatable mark", () => {
    const north = catamaranSvg(0);
    const east = catamaranSvg(90);
    const south = catamaranSvg(180);
    assert.match(north, /data-bow="north"/);
    assert.match(north, /data-heading="0"/);
    assert.match(east, /data-heading="90"/);
    assert.match(south, /data-heading="180"/);
    assert.match(north, /data-marker-rotatable/);
    assert.doesNotMatch(north, /transform:rotate/);
    assert.match(north, /<svg /);
    assert.doesNotMatch(north, /<img /);
  });
});

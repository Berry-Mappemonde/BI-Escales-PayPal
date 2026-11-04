import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { summarizeAmpTraffic, trafficKind } from "./ampRules.js";

describe("ampRules", () => {
  it("reads ProtectedSeas entry / speed", () => {
    assert.equal(trafficKind(1, 3), "forbidden");
    assert.equal(trafficKind(3, 1), "forbidden");
    assert.equal(trafficKind(2, 3), "regulated");
    assert.equal(trafficKind(0, 3), "allowed");
    assert.equal(trafficKind(3, 3), "unknown");
  });

  it("signals a regulated crossing first", () => {
    const out = summarizeAmpTraffic([
      { name: "Loin", entry: 2, speed: 3, nm: 12, inside: false },
      { name: "Cabrera", entry: 2, speed: 3, nm: 0, inside: true },
    ], "fr");
    assert.equal(out.kind, "regulated-inside");
    assert.match(out.line, /Circulation régulée/);
    assert.match(out.line, /Cabrera/);
  });

  it("signals a nearby regulated MPA when the boat is not inside", () => {
    const out = summarizeAmpTraffic([
      { name: "Pertuis", entry: 2, speed: 3, nm: 3.6, inside: false },
    ], "fr");
    assert.equal(out.kind, "regulated-near");
    assert.match(out.line, /à proximité/);
    assert.match(out.line, /3,6 nm/);
  });
});

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { resolveFollowSpeed } from "./expeditionSpeed.js";

const here = dirname(fileURLToPath(import.meta.url));

describe("useExpeditionSpeed", () => {
  it("en Suivre, la vitesse est celle de l'horloge (0 à quai)", () => {
    assert.deepEqual(resolveFollowSpeed(null), { knots: null, kind: null, live: false });
    assert.deepEqual(resolveFollowSpeed({
      speedKnots: 7.4, atQuay: false, regime: "hindcast",
    }), { knots: 7.4, kind: "hindcast", live: false });
    assert.deepEqual(resolveFollowSpeed({
      speedKnots: 11.9, atQuay: true, regime: "hindcast",
    }), { knots: 0, kind: "hindcast", live: false });
  });

  it("ne calcule plus une vitesse concurrente quand follow est vrai", () => {
    const src = readFileSync(join(here, "useExpeditionSpeed.js"), "utf8");
    assert.match(src, /if \(follow\) return/);
    assert.match(src, /resolveFollowSpeed\(clockSample\)/);
    assert.doesNotMatch(src, /clockReady/);
  });
});

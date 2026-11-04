/**
 * Parité polaire client / serveur.
 * Mêmes 20 cas TWA × TWS que server/tests/test_polar_parity.py
 * (fixture server/tests/fixtures/polar_cases.json) → |Δ| ≤ 0,05 kn.
 */
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { polarBoatSpeed } from "./polarSpeed.js";

const FIXTURE = JSON.parse(readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), "../../server/tests/fixtures/polar_cases.json"),
  "utf8",
));

describe("Parité polaire JS / fixture Python", () => {
  it("20 cas TWA × TWS, même vitesse à 0,05 kn", () => {
    const { polar, cases, tolerance_kn: tol } = FIXTURE;
    assert.equal(cases.length, 20);
    for (const { twa, tws, expected_kn: expected } of cases) {
      const kn = polarBoatSpeed(polar, twa, tws);
      assert.ok(Number.isFinite(kn), `TWA ${twa} TWS ${tws} → ${kn}`);
      assert.ok(
        Math.abs(kn - expected) <= tol,
        `TWA ${twa} TWS ${tws} : JS ${kn} ≠ ${expected} (tol ${tol})`,
      );
    }
  });

  it("TWA −90° = +90° (symétrie babord / tribord)", () => {
    const { polar } = FIXTURE;
    assert.equal(polarBoatSpeed(polar, 90, 12), polarBoatSpeed(polar, -90, 12));
  });
});

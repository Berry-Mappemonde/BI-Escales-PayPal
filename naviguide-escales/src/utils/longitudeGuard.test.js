/*
 * Garde-fou : aucun repli de longitude écrit à la main dans src/ hors de
 * utils/geo.js. L'antiméridien a été corrigé plusieurs fois parce que le
 * calcul existait en plusieurs copies : chaque correctif en réparait une.
 * Utilisez wrapLon, unwrapLon, deltaLon ou lerpLon (utils/geo.js).
 * Seule exception : les caps (lerpHeading), qui ne sont pas des longitudes.
 */
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");
const HELPER = "utils/geo.js";
const AD_HOC = [
  /[-+]=\s*360\b/,
  /[+-]\s*(180|540)\s*\)\s*%\s*360/,
];
// Fixtures : copie figée du code Blue Intelligence, vérifiée telle quelle par recetteAg.test.js.
const SKIP_DIRS = new Set(["fixtures", "node_modules"]);
const ALLOWED = new Set([
  "map/filmCamera.js|while (d > 180) d -= 360;",
  "map/filmCamera.js|while (d < -180) d += 360;",
]);

function* sources(dir) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      if (!SKIP_DIRS.has(entry.name)) yield* sources(full);
    } else if (/\.(js|jsx|mjs)$/.test(entry.name) && !/\.test\.js$/.test(entry.name)) {
      yield [relative(SRC, full).split(sep).join("/"), full];
    }
  }
}

const code = (line) => line.replace(/\/\/.*$/, "").trim();

describe("garde-fou longitudes (src/)", () => {
  it("aucun repli de longitude écrit à la main hors de utils/geo.js", () => {
    const offenders = [];
    for (const [rel, full] of sources(SRC)) {
      if (rel === HELPER) continue;
      readFileSync(full, "utf8").split("\n").forEach((line, i) => {
        const c = code(line);
        if (!c || !AD_HOC.some((re) => re.test(c))) return;
        if (ALLOWED.has(`${rel}|${c}`)) return;
        offenders.push(`${rel}:${i + 1}: ${c}`);
      });
    }
    assert.deepEqual(offenders, [], `Repli de longitude à la main ; passez par utils/geo.js :\n${offenders.join("\n")}`);
  });

  it("les exceptions listées existent encore", () => {
    const present = new Set();
    for (const [rel, full] of sources(SRC)) {
      for (const line of readFileSync(full, "utf8").split("\n")) present.add(`${rel}|${code(line)}`);
    }
    for (const key of ALLOWED) assert.ok(present.has(key), `exception inutile : ${key}`);
  });

  it("le motif attrape les replis connus", () => {
    for (const s of ["while (x > 180) x -= 360;", "lon += 360;", "Math.abs(((a - b + 540) % 360) - 180)", "((lon + 180) % 360) - 180"]) {
      assert.ok(AD_HOC.some((re) => re.test(s)), s);
    }
    for (const s of ["((raw % 360) + 360) % 360", "if (d > 180) d = 360 - d;", "[x, x + 360, x - 360]"]) {
      assert.ok(!AD_HOC.some((re) => re.test(s)), s);
    }
  });
});

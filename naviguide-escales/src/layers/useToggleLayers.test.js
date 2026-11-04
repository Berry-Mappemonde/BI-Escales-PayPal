import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, it } from "node:test";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(join(here, "useToggleLayers.js"), "utf8");
const app = readFileSync(join(here, "../App.jsx"), "utf8");

function loadNextRestricted(source) {
  const start = source.indexOf("export function nextRestricted");
  assert.ok(start > 0, "nextRestricted introuvable");
  const end = source.indexOf("\n}", start);
  const body = source.slice(start, end + 2).replace(/^export /m, "");
  return new Function(`${body}\nreturn nextRestricted;`)();
}

const nextRestricted = loadNextRestricted(src);

const GATED = ["setShowBalisage", "setShowBathymetry", "setShowFonds", "setShowCables"];

describe("useToggleLayers — sac de couches stable", () => {
  it("mémorise les setters filtrés pour ne pas republier le sac à chaque rendu", () => {
    // MapScene republie ce sac dans un setState. Une fonction neuve à chaque
    // rendu invalide le useMemo, le setState relance le rendu, et l'onglet
    // meurt en entrant dans Tracer (boucle sans plafond en production).
    for (const name of GATED) {
      assert.match(src, new RegExp(`const ${name} = useCallback\\(`));
      assert.doesNotMatch(src, new RegExp(`const ${name} = gatedSet\\(`));
    }
    const bagAt = src.indexOf("return useMemo(() => ({");
    assert.ok(bagAt > 0, "sac mémoïsé introuvable");
    const bag = src.slice(bagAt);
    for (const name of GATED) {
      assert.match(bag, new RegExp(`${name},`));
    }
  });

  it("garde le refus du bandeau « pas pour la navigation » sur ces quatre couches", () => {
    assert.match(src, /gateRef\.current\?\.onNeed\?\.\(kind\)/);
    assert.match(src, /return v;/);
    for (const kind of ["balisage", "bathymetry", "fonds", "cables"]) {
      assert.match(src, new RegExp(`"${kind}"`));
    }
    const gated = src.slice(src.indexOf("const gatedSet"), src.indexOf("const setShowBalisage"));
    assert.match(gated, /gateRef\.current\?\.onNeed\?\.\(kind\)/);
    assert.doesNotMatch(gated, /setter\(\(v\)/);
  });
});

describe("cadenas — allumage sans second clic, vue monde comprise", () => {
  it("sans accord, allumer garde l'état éteint ; avec accord, le premier passage allume", () => {
    const toggle = (v) => !v;
    assert.equal(nextRestricted(false, toggle, false), false);
    assert.equal(nextRestricted(false, true, false), false);
    assert.equal(nextRestricted(false, toggle, true), true);
    assert.equal(nextRestricted(false, true, true), true);
    assert.equal(nextRestricted(true, toggle, true), false);
    assert.equal(nextRestricted(true, toggle, false), false);
    assert.equal(nextRestricted(true, false, false), false);
  });

  it("Accepter écrit le calque brut, sans plancher de zoom", () => {
    assert.match(src, /gate\.commit = commit/);
    assert.match(src, /setShowBalisageRaw\(true\)/);
    assert.match(src, /setShowBathymetryRaw\(true\)/);
    assert.match(src, /setShowFondsRaw\(true\)/);
    assert.match(src, /setShowCablesRaw\(true\)/);
    assert.match(src, /minZoom:\s*0/);
    const gated = src.slice(src.indexOf("const gatedSet"), src.indexOf("const setShowBalisage"));
    assert.doesNotMatch(gated, /getZoom|minZoom/);
    const enableAt = app.indexOf("const enablePendingRestricted");
    const enable = app.slice(enableAt, app.indexOf("useLayoutEffect", enableAt));
    assert.match(enable, /gateRef\.current\?\.commit/);
    assert.match(enable, /commit\(kind\)/);
    assert.doesNotMatch(enable, /getZoom|minZoom|ne convient/);
    const accept = app.slice(app.indexOf("onAccept={() => {"), app.indexOf("onAccept={() => {") + 500);
    assert.match(accept, /gateRef\.current\.allowed = true/);
    assert.match(accept, /enablePendingRestricted\(kind\)/);
  });
});

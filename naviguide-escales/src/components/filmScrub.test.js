import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { isKeyboardClick, scrubKeyTarget } from "./filmScrub.js";

const here = dirname(fileURLToPath(import.meta.url));
const bar = readFileSync(join(here, "SimulationFilmBar.jsx"), "utf8");

describe("film scrub keyboard controls", () => {
  it("moves by 1%, 10% with Shift, and to either endpoint", () => {
    assert.equal(scrubKeyTarget("ArrowRight", false, 500, 1000), 510);
    assert.equal(scrubKeyTarget("ArrowLeft", false, 500, 1000), 490);
    assert.equal(scrubKeyTarget("ArrowRight", true, 500, 1000), 600);
    assert.equal(scrubKeyTarget("ArrowLeft", true, 50, 1000), 0);
    assert.equal(scrubKeyTarget("ArrowRight", true, 950, 1000), 1000);
    assert.equal(scrubKeyTarget("Home", false, 500, 1000), 0);
    assert.equal(scrubKeyTarget("End", false, 500, 1000), 1000);
    assert.equal(scrubKeyTarget("PageUp", false, 500, 1000), 600);
  });

  it("ignores unrelated keys and an empty bar", () => {
    assert.equal(scrubKeyTarget("Enter", false, 500, 1000), null);
    assert.equal(scrubKeyTarget(" ", false, 500, 1000), null);
    assert.equal(scrubKeyTarget("ArrowRight", false, 0, 0), null);
  });

  it("distinguishes keyboard generated clicks", () => {
    assert.equal(isKeyboardClick({ detail: 0, isTrusted: true }), true);
    assert.equal(isKeyboardClick({ detail: 0, isTrusted: false }), false);
    assert.equal(isKeyboardClick({ detail: 0 }), false);
    assert.equal(isKeyboardClick({ detail: 1, isTrusted: true }), false);
  });

  it("exposes localized slider semantics and keyboard handling", () => {
    assert.match(bar, /data-testid="film-scrub"/);
    assert.match(bar, /role="slider"/);
    assert.match(bar, /aria-label=\{t\("filmScrub"\)\}/);
    assert.match(bar, /aria-valuemin=\{0\}/);
    assert.match(bar, /aria-valuemax=\{Math\.round\(barTotal \|\| 0\)\}/);
    assert.match(bar, /aria-valuenow=\{Math\.round\(barNm \|\| 0\)\}/);
    assert.match(bar, /aria-valuetext=\{scrubValueText\}/);
    assert.match(bar, /t\("filmScrubValue", \{\s*at: Math\.round\(barNm \|\| 0\)\.toLocaleString\(nmLocale\),\s*total: Math\.round\(barTotal \|\| 0\)\.toLocaleString\(nmLocale\),\s*\}\)/);
    assert.match(bar, /onKeyDown=\{onBarKeyDown\}/);
    assert.match(bar, /if \(isKeyboardClick\(e\)\) return;/);
    const app = readFileSync(join(here, "..", "App.jsx"), "utf8");
    assert.match(app, /e\.target\?\.closest\?\.\("\[role='slider'\]"\) && \/\^\(Arrow\|Home\$\|End\$\|Page\)\/\.test\(e\.code\)\) return;/);
  });
});

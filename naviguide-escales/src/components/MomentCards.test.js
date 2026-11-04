import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(join(here, "MomentCards.jsx"), "utf8");

describe("MomentCards — : aucune publication hors film", () => {
  it("ne publie plus la carte NOW dans la bulle hors film", () => {
    assert.doesNotMatch(src, /publishEventBubble/);
    assert.doesNotMatch(src, /isNowAlertOrDecision/);
    assert.doesNotMatch(src, /__naviguideEventBubble/);
    const nowFn = src.slice(src.indexOf("export const MomentNowCard"), src.indexOf("export const FreeMomentBlock"));
    assert.doesNotMatch(nowFn, /useEffect/);
  });
});

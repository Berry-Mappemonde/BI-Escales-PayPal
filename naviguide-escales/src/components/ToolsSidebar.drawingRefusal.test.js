import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, it } from "node:test";
import { drawingRefusalPhrase } from "../hooks/useRouteDrawing.js";
import fr from "../i18n/fr.js";
import en from "../i18n/en.js";

const here = dirname(fileURLToPath(import.meta.url));
const tools = readFileSync(join(here, "ToolsSidebar.jsx"), "utf8");
const box = tools.slice(tools.indexOf("function DrawingBox"), tools.indexOf("function ExpeditionBox"));

describe("cadre du tracé — refus 422", () => {
  it("écrit la phrase terre ou traversée dans drawing-box", () => {
    assert.ok(box.includes('data-testid="drawing-box"'));
    assert.match(box, /drawingRefusalPhrase\(drawing\?\.notice, t\)/);
    assert.match(box, /\{refusal \?/);
    assert.equal(drawingRefusalPhrase("on_land", (key) => fr[key]), "Point sur terre : non ajouté");
    assert.equal(drawingRefusalPhrase("crosses_land", (key) => fr[key]), "La ligne droite traverse la terre");
    assert.equal(drawingRefusalPhrase("on_land", (key) => en[key]), "Point on land: not added");
    assert.equal(drawingRefusalPhrase("crosses_land", (key) => en[key]), "Straight line crosses land");
    assert.equal(drawingRefusalPhrase("server_error", (key) => fr[key]), "");
  });
});

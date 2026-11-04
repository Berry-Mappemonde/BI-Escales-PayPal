import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const app = readFileSync(join(here, "..", "App.jsx"), "utf8");

describe("openEscaleFromUi — pas d'ouverture de panneau", () => {
  it("n'appelle plus setSidebarOpen", () => {
    const start = app.indexOf("const openEscaleFromUi");
    const end = app.indexOf("const replayControls");
    assert.ok(start >= 0 && end > start, "openEscaleFromUi introuvable");
    const block = app.slice(start, end);
    assert.match(block, /openEscaleSheet\(next\)/);
    assert.doesNotMatch(block, /setSidebarOpen/);
  });

  it("un escaleStop ne rouvre plus le panneau gauche", () => {
    assert.doesNotMatch(app, /if \(escaleStop && !replay\.active\) setSidebarOpen\(true\)/);
  });
});

describe("onSeekEscale — : liste informative dans tous les modes", () => {
  it("ne passe plus handleSidebarSeek à la liste", () => {
    assert.doesNotMatch(app, /onSeekEscale=/);
    assert.doesNotMatch(app, /onSeekEscale=\{isSuivre \? undefined : handleSidebarSeek\}/);
  });
});

describe("handleSidebarSeek — : preview utilisateur", () => {
  it("en Suivre, setUserPreview(true) avant pause+seek", () => {
    const start = app.indexOf("const handleSidebarSeek");
    const end = app.indexOf("const handleSeekJournal");
    assert.ok(start >= 0 && end > start, "handleSidebarSeek introuvable");
    const block = app.slice(start, end);
    assert.match(block, /if \(isSuivre\) setUserPreview\(true\)/);
    assert.match(block, /playback\.pause/);
    assert.match(block, /playback\.seek/);
    const preview = block.indexOf("setUserPreview(true)");
    const pause = block.indexOf("playback.pause");
    assert.ok(preview >= 0 && pause > preview, "preview avant pause");
  });
});

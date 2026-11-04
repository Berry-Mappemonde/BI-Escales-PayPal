import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { exitDocumentFullscreen, isCinemaKey, restoreShowLayers, snapshotShowLayers } from "./cinemaHotkey.js";

describe("isCinemaKey", () => {
  it("C seule allume le cinéma", () => {
    assert.equal(isCinemaKey({ code: "KeyC", metaKey: false, ctrlKey: false }), true);
  });

  it("ignore ⌘C et Ctrl+C (Copier)", () => {
    assert.equal(isCinemaKey({ code: "KeyC", metaKey: true, ctrlKey: false }), false);
    assert.equal(isCinemaKey({ code: "KeyC", metaKey: false, ctrlKey: true }), false);
  });

  it("Stop quitte le plein écran et rend les calques", () => {
    assert.equal(exitDocumentFullscreen(null), false);
    assert.equal(exitDocumentFullscreen({}), false);
    let exited = 0;
    const doc = {
      fullscreenElement: {},
      exitFullscreen() {
        exited += 1;
        return Promise.resolve();
      },
    };
    assert.equal(exitDocumentFullscreen(doc), true);
    assert.equal(exited, 1);
    const layers = { showZee: false, loadingZee: false, setShowZee(v) { layers.showZee = v; } };
    const saved = snapshotShowLayers({ showZee: true, loadingZee: true, setShowZee() {} });
    assert.deepEqual(saved, { showZee: true });
    assert.equal(restoreShowLayers(layers, saved), 1);
    assert.equal(layers.showZee, true);
    assert.equal(restoreShowLayers(layers, saved), 0);
  });

  it("ignore les autres touches", () => {
    assert.equal(isCinemaKey({ code: "KeyL", metaKey: false, ctrlKey: false }), false);
    assert.equal(isCinemaKey(null), false);
  });
});

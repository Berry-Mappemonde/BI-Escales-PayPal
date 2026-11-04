import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { ScenePlaybackController } from "./ScenePlaybackController.js";

const flat = {
  totalNm: 100,
  totalFilmNm: 100,
  points: [
    { lat: 0, lon: 0, cumNm: 0, filmCum: 0 },
    { lat: 1, lon: 1, cumNm: 100, filmCum: 100 },
  ],
};

describe("ScenePlaybackController", () => {
  it("garde le playhead hors de React et publie immédiatement les commandes", () => {
    const frames = [];
    const publications = [];
    const controller = new ScenePlaybackController({
      onFrame: (snapshot) => frames.push(snapshot),
      onPublish: (snapshot) => publications.push(snapshot),
      requestFrame: () => 1,
      cancelFrame: () => {},
    });

    controller.configure({ flat, marks: [], boatKnots: 8, enabled: true, stopAuto: false });
    controller.seek(42, { jump: true });
    controller.setProfile("fast");

    assert.equal(controller.snapshot().nm, 42);
    assert.equal(controller.snapshot().profile, "fast");
    assert.equal(controller.snapshot().jumpToken, 1);
    assert.ok(frames.length >= 3);
    assert.ok(publications.length >= 3);
    controller.destroy();
  });

  it("borne le seek et arrête la lecture", () => {
    const controller = new ScenePlaybackController({
      requestFrame: () => 1,
      cancelFrame: () => {},
    });
    controller.configure({ flat, marks: [], boatKnots: 8, enabled: true, stopAuto: false });
    controller.seek(999);
    controller.play();
    controller.pause();

    assert.equal(controller.snapshot().nm, 100);
    assert.equal(controller.snapshot().playing, false);
    controller.destroy();
  });

  it("émet à la frame en mode film, et reste à 125 ms hors film", () => {
    const frames = [];
    const controller = new ScenePlaybackController({
      onFrame: (snapshot) => frames.push(snapshot),
      requestFrame: () => 1,
      cancelFrame: () => {},
    });
    controller.configure({ flat, marks: [], boatKnots: 8, enabled: true, filmActive: false });
    const afterConfig = frames.length;
    controller.lastFrameAt = 1000;
    controller.emitFrame(false, 1040);
    assert.equal(frames.length, afterConfig, "hors film : intervalle 125 ms");
    controller.emitFrame(false, 1130);
    assert.ok(frames.length > afterConfig, "hors film : un frame après 125 ms");

    controller.configure({ filmActive: true });
    const atFilm = frames.length;
    controller.lastFrameAt = 2000;
    controller.emitFrame(false, 2008);
    assert.ok(frames.length > atFilm, "film : un frame dès la frame suivante");
    controller.destroy();
  });
});

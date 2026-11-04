import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { nextStationAfter, stepPlayback, dwellMsForProfile, dwellMsForStation, portDwellDays, shouldPauseAtStop } from "./stationDwell.js";

const stations = [
  { filmNm: 0, name: "Départ", kind: "start" },
  { filmNm: 100, name: "Horta", kind: "waypoint" },
  { filmNm: 250, name: "Halifax", kind: "waypoint" },
];

describe("stationDwell", () => {
  it("ignores the start at 0 nm", () => {
    assert.equal(nextStationAfter(-1, stations).name, "Horta");
    assert.equal(nextStationAfter(0, stations).name, "Horta");
  });

  it("stops at the stopover and sets a dwell", () => {
    const r = stepPlayback({
      filmNm: 99,
      deltaMs: 1000,
      rate: 2,
      stations,
      maxFilmNm: 400,
      dwellMs: 1800,
    });
    assert.equal(r.filmNm, 100);
    assert.equal(r.dwellMsLeft, 1800);
    assert.equal(r.holding, true);
    assert.equal(r.arrived.name, "Horta");
  });

  it("stays still during the dwell", () => {
    const r = stepPlayback({
      filmNm: 100,
      dwellMsLeft: 800,
      deltaMs: 300,
      rate: 40,
      stations,
      maxFilmNm: 400,
      dwellMs: 1800,
    });
    assert.equal(r.filmNm, 100);
    assert.equal(r.dwellMsLeft, 500);
    assert.equal(r.holding, true);
  });

  it("resumes after the dwell ends", () => {
    const r = stepPlayback({
      filmNm: 100,
      dwellMsLeft: 200,
      deltaMs: 500,
      rate: 10,
      stations,
      maxFilmNm: 400,
      dwellMs: 1800,
    });
    assert.equal(r.holding, false);
    assert.ok(r.filmNm > 100);
    assert.equal(r.dwellMsLeft, 0);
  });

  it("jump skips the dwell", () => {
    const r = stepPlayback({
      filmNm: 100,
      dwellMsLeft: 1800,
      deltaMs: 16,
      rate: 10,
      stations,
      maxFilmNm: 400,
      dwellMs: 1800,
      jump: true,
    });
    assert.equal(r.holding, false);
    assert.equal(r.dwellMsLeft, 0);
  });

  it("profil fast = pause plus courte", () => {
    assert.ok(dwellMsForProfile("fast") < dwellMsForProfile("real"));
  });

  it("Cayenne séjourne 3 jours, Halifax 1, Saint-Maur aucun", () => {
    assert.equal(portDwellDays("Cayenne (Guyane)"), 3);
    assert.equal(portDwellDays("Halifax (Nouvelle-Écosse)"), 1);
    assert.equal(portDwellDays("Saint-Maur (Berry, Indre)"), 0);
    assert.equal(dwellMsForStation({ name: "Cayenne (Guyane)" }, "normal"), dwellMsForProfile("normal"));
    assert.equal(dwellMsForStation({ name: "Halifax (Nouvelle-Écosse)" }, "normal"), Math.round(dwellMsForProfile("normal") / 3));
    assert.equal(dwellMsForStation({ name: "Saint-Maur (Berry, Indre)" }, "normal"), 0);
  });

  it("Stop auto ON pause à l’escale, OFF traverse", () => {
    const arrived = { name: "Ajaccio" };
    assert.equal(shouldPauseAtStop(true, arrived), true);
    assert.equal(shouldPauseAtStop(false, arrived), false);
    assert.equal(shouldPauseAtStop(true, null), false);
  });
});

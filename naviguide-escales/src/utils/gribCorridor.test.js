import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { corridorBboxOk, corridorForBoat, pointInBbox } from "./gribCorridor.js";

describe("couloir GRIB", () => {
  it("accepte un rectangle bateau, refuse un globe", () => {
    assert.equal(corridorBboxOk([10, 16, -65, -58]), true);
    assert.equal(corridorBboxOk([-80, 80, -180, 180]), false);
    assert.equal(corridorBboxOk(null), false);
  });

  it("recentre sur le bateau si le bbox serveur est ailleurs", () => {
    const server = [-3, 3, -103, -96];
    assert.equal(pointInBbox(server, 0.1, -99), true);
    assert.equal(pointInBbox(server, -22, 166), false);
    const local = corridorForBoat(server, -22.3, 166.4);
    assert.ok(local[0] < -22.3 && local[1] > -22.3);
    assert.ok(Math.abs(local[2] - 166.4) < 4);
  });

  it("Pacific : bbox et bateau sur des copies ±360°", () => {
    const unwrapped = [-25, -20, -194, -188];
    assert.equal(pointInBbox(unwrapped, -22.7, -191.16), true);
    assert.equal(pointInBbox(unwrapped, -22.7, 168.84), true);
    const wrapped = [-25, -20, 165, 172];
    assert.equal(pointInBbox(wrapped, -22.7, -191.16), true);
    const aroundClock = corridorForBoat([-3, 3, -103, -96], -22.7, -191.16);
    assert.ok(Math.abs(aroundClock[2] + 191.16) < 4);
    const aroundCam = corridorForBoat([-3, 3, -103, -96], -22.7, 168.84);
    assert.ok(Math.abs(aroundCam[2] - 168.84) < 4);
  });
});

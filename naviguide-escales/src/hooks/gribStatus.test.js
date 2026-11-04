import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { officialGribQuery, officialGribStatus, officialGribWarning } from "./gribStatus.js";

describe("officialGribStatus", () => {
  it("reste pending sans position — pas absente à l’ouverture", () => {
    assert.equal(officialGribStatus({
      enabled: true,
      grib: { status: "absent" },
      pending: false,
      positioned: false,
    }), "pending");
    assert.equal(officialGribWarning({ enabled: true, status: "pending" }), null);
  });

  it("ready dès que le fichier est là", () => {
    assert.equal(officialGribStatus({
      enabled: true,
      grib: { status: "ready" },
      pending: false,
      positioned: true,
    }), "ready");
  });

  it("absente seulement après un fetch positionné raté", () => {
    assert.equal(officialGribStatus({
      enabled: true,
      grib: { status: "absent" },
      pending: false,
      positioned: true,
    }), "absent");
    assert.equal(officialGribWarning({ enabled: true, status: "absent" }), "dernière prévision absente");
  });

  it("n’émet pas de query sans horloge — évite un GRIB Atlantique au load", () => {
    assert.equal(officialGribQuery(null), null);
    assert.equal(officialGribQuery({}), null);
  });

  it("enveloppe la lon pour Open-Meteo (−187 → 173)", () => {
    const clock = {
      t0: "2026-05-15T08:00:00.000Z",
      vertices: [{
        tHours: 0,
        lat: -22.02,
        lon: -187.94,
        filmNm: 18700,
        sailNm: 18700,
        vehicle: "main",
      }],
    };
    const q = officialGribQuery(clock, new Date("2026-05-15T08:00:00.000Z"));
    assert.equal(q.lat, -22.02);
    assert.ok(q.lon > 170 && q.lon < 174);
  });
});

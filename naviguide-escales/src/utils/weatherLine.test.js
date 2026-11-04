import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { countOpenMeteo, weatherLine, WEATHER_LINE } from "./weatherLine.js";

describe("weatherLine", () => {
  it("une ligne GFS + GFS-Wave (Open-Meteo) en Suivre prêt", () => {
    assert.equal(weatherLine({ isSuivre: true, gribReady: true }), WEATHER_LINE);
    assert.equal(countOpenMeteo(WEATHER_LINE), 1);
  });

  it("vide en Simulation (climatologie)", () => {
    assert.equal(weatherLine({ isSuivre: false, gribReady: true }), "");
    assert.equal(weatherLine({ isSuivre: true, gribReady: false }), "");
  });
});

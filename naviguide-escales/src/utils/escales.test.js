import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { dropRepeatedStops, nextEscaleIndex, nextEscaleStop } from "./escales.js";

const stops = [
  { name: "La Rochelle", flag: "fr" },
  { name: "Point intermédiaire Avant Corse", flag: "" },
  { name: "Ajaccio (Corse)", flag: "corse" },
  { name: "Point intermédiaire Après Corse", flag: "" },
];

describe("nextEscaleIndex", () => {
  it("keeps a stopover", () => {
    assert.equal(nextEscaleIndex(stops, 0), 0);
    assert.equal(nextEscaleIndex(stops, 2), 2);
  });

  it("skips an intermediate point to the next stopover", () => {
    assert.equal(nextEscaleIndex(stops, 1), 2);
    assert.equal(nextEscaleStop(stops, 1).stop.name, "Ajaccio (Corse)");
  });

  it("stays on the last intermediate if there is no further stopover", () => {
    assert.equal(nextEscaleIndex(stops, 3), 3);
  });

  it("retire Cayenne en double et garde le retour à La Rochelle", () => {
    const marks = [
      { name: "La Rochelle" },
      { name: "Cayenne (Guyane)" },
      { name: "Cayenne (Guyane)" },
      { name: "Papeete (Polynésie française)" },
      { name: "La Rochelle" },
    ];
    const names = dropRepeatedStops(marks).map((m) => m.name);
    assert.deepEqual(names, [
      "La Rochelle",
      "Cayenne (Guyane)",
      "Papeete (Polynésie française)",
      "La Rochelle",
    ]);
  });
});

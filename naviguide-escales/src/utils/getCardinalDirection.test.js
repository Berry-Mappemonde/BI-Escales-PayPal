import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { getCardinalDirection } from "./getCardinalDirection.js";

describe("getCardinalDirection", () => {
  it("accepte un nombre (popup satellite)", () => {
    assert.equal(getCardinalDirection(0), "N");
    assert.equal(getCardinalDirection(90), "E");
    assert.equal(getCardinalDirection(180), "S");
    assert.equal(getCardinalDirection(255), "OSO");
    assert.equal(getCardinalDirection(255, "en"), "WSW");
    assert.equal(getCardinalDirection(312, "en"), "NW");
    assert.equal(getCardinalDirection(312, "fr"), "NO");
    assert.equal(getCardinalDirection(360), "N");
  });

  it("accepte encore { degrees }", () => {
    assert.equal(getCardinalDirection({ degrees: 255 }), "OSO");
  });

  it("ne jette pas si le vent est absent", () => {
    assert.equal(getCardinalDirection(undefined), "");
    assert.equal(getCardinalDirection(null), "");
    assert.equal(getCardinalDirection({}), "");
  });
});

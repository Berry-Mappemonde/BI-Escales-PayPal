import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { enDecimals, localizeStoredFact } from "./iciMaintenant.js";

describe("revue EN 0951 : séparateur décimal des faits stockés", () => {
  it("« 2,7 nm » devient « 2.7 nm » en EN et reste tel quel en FR", () => {
    assert.equal(enDecimals("Marina (2,7 nm)", "en"), "Marina (2.7 nm)");
    assert.equal(enDecimals("Marina (2,7 nm)", "fr"), "Marina (2,7 nm)");
    assert.equal(enDecimals("1,500 nm", "en"), "1,500 nm");
    assert.equal(enDecimals("1,72 nm/h · 4,0 d · 21,7 d", "en"), "1.72 nm/h · 4.0 d · 21.7 d");
    assert.equal(enDecimals("1,72 nm/h · 4,0 d", "fr"), "1,72 nm/h · 4,0 d");
    assert.match(localizeStoredFact("à 2,7 nm", "en"), /2\.7 nm/);
  });
});

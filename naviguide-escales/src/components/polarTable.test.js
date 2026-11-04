import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { polarBoatSpeed } from "../engine/polarSpeed.js";

const here = dirname(fileURLToPath(import.meta.url));
const tools = readFileSync(join(here, "ToolsSidebar.jsx"), "utf8");
const fixture = JSON.parse(readFileSync(
  join(here, "../../server/tests/fixtures/polar_cases.json"),
  "utf8",
));

describe("polar table equals /api/v1/polar/.../speed", () => {
  it("reads each cell through polarBoatSpeed, including TWA 90° / TWS 12 kn", () => {
    assert.match(tools, /polarBoatSpeed\(raw, twa, tws\)/);
    assert.match(tools, /data-testid=\{`polar-speed-\$\{twa\}-\$\{tws\}`\}/);
    const expected = fixture.cases.find((row) => row.twa === 90 && row.tws === 12);
    const kn = polarBoatSpeed(fixture.polar, 90, 12);
    assert.equal(kn, expected.expected_kn);
    assert.equal(kn, 10.6);
  });
});

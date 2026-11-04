import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const hook = readFileSync(join(here, "useIciAlong.js"), "utf8");
const app = readFileSync(join(here, "..", "App.jsx"), "utf8");

describe("useIciAlong", () => {
  it("coupe les GET /ici en vol au cleanup ; pas Berry pendant le dessin", () => {
    assert.match(hook, /thin: "1"/);
    assert.match(hook, /const inflight = \[\]/);
    assert.match(hook, /inflight\.push\(ctrl\)/);
    assert.match(hook, /for \(const c of inflight\) c\.abort\(\)/);
    assert.match(app, /enabled: Boolean\(cast && routeReady\) && !replay\.active && !drawingMode/);
    assert.match(app, /draftWarmerRef\.current\.schedule\(toGeoJson\(\)\)/);
  });
});

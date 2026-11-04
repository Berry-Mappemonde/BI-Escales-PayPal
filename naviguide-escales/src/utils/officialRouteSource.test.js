import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { existsSync, lstatSync, readFileSync, readlinkSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "../..");
const publicRoute = join(root, "public/route.geojson");
const canonical = join(root, "../backend/data/route.geojson");
const LINK = "../../backend/data/route.geojson";

describe("source unique de la route Berry", () => {
  it("le fichier public se lit et porte le découpage antiméridien", () => {
    const fc = JSON.parse(readFileSync(publicRoute, "utf8"));
    const wallis = (fc.features || []).filter(
      (f) => f.properties?.from?.includes("Wallis") && f.properties?.to?.includes("Nouméa"),
    );
    assert.equal(wallis.length, 2);
    assert.equal(fc.features.length, 72);
  });

  it("dans le monodépôt, public/route.geojson est le lien vers backend/data", () => {
    if (!existsSync(canonical)) return;
    const st = lstatSync(publicRoute);
    assert.equal(st.isSymbolicLink(), true);
    assert.equal(readlinkSync(publicRoute), LINK);
    assert.equal(readFileSync(publicRoute).equals(readFileSync(canonical)), true);
  });
});

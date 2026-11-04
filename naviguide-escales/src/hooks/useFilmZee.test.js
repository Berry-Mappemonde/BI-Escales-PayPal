import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { FILM_ZEE_STEP_DEG, filmZeeBucket, filmZeeForBucket } from "./useFilmZee.js";

const src = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "useFilmZee.js"), "utf8");

describe("useFilmZee — pas de temps du film", () => {
  it("Nouméa (−22.27, 166.44) tient dans un seul pas, pas un appel par image", () => {
    assert.equal(FILM_ZEE_STEP_DEG, 0.2);
    const a = filmZeeBucket(-22.27, 166.44);
    const b = filmZeeBucket(-22.271, 166.441);
    assert.equal(a, b);
    assert.equal(a, "-22.2:166.4");
    assert.notEqual(filmZeeBucket(-22.27, 166.44), filmZeeBucket(-18.1, 178.4));
  });

  it("une longitude dépliée est repliée avant le pas", () => {
    assert.equal(filmZeeBucket(-22.27, 166.44 + 360), filmZeeBucket(-22.27, 166.44));
  });

  it("le hook lit GET /zee/at et ne garde pas la ZEE du pas précédent", () => {
    assert.match(src, /\/zee\/at\?lat=/);
    assert.match(src, /setZee\(null\)/);
    assert.match(src, /filmZeeForBucket\(zee, bucket\)/);
    assert.doesNotMatch(src, /Tavily|Nebius|Nemotron/);
    const adelaide = { name: "Adelaide Exclusive Economic Zone", mrgid: 8323, bucket: filmZeeBucket(-35, 138.6) };
    const noumea = filmZeeBucket(-22.27, 166.44);
    assert.equal(filmZeeForBucket(adelaide, noumea), null);
    assert.equal(filmZeeForBucket(null, noumea), null);
    assert.equal(filmZeeForBucket(adelaide, ""), null);
    const fresh = { name: "French Exclusive Economic Zone (New Caledonia)", mrgid: 8312, bucket: noumea };
    assert.equal(filmZeeForBucket(fresh, noumea), fresh);
  });
});

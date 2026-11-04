import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { releaseFilmMap, restoreFollowView } from "./useFilmCamera.js";

describe("FM1 — Stop rend la carte", () => {
  it("ne recentre pas sur le bateau du film et réaffiche les tuiles complètes", () => {
    const calls = [];
    const img = { complete: true, naturalWidth: 32, style: { visibility: "hidden" } };
    const broken = { complete: true, naturalWidth: 0, style: { visibility: "hidden" } };
    const map = {
      invalidateSize() { calls.push("size"); },
      setView() { calls.push("view"); },
      eachLayer(fn) {
        fn({
          _url: "https://tiles.example/osm/{z}/{x}/{y}.png",
          _tiles: { a: { el: img }, b: { el: broken } },
          redraw() { calls.push("redraw"); },
        });
        fn({ redraw() { calls.push("other"); } });
      },
    };
    const out = restoreFollowView({ map }, { lat: -22.2, lon: 166.4 });
    assert.equal(out.view, "suivre");
    assert.equal(out.follow, true);
    assert.equal(out.movedToFilm, false);
    assert.equal(calls.includes("view"), false);
    assert.equal(calls.includes("size"), true);
    assert.equal(img.style.visibility, "");
    assert.equal(broken.style.visibility, "hidden");
    assert.equal(releaseFilmMap(null), false);
  });
});

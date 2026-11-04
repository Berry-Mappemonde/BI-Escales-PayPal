import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { atlasNoticeFromBody } from "./useAtlasLookup.js";

describe("atlasNoticeFromBody", () => {
  it("une réponse indisponible n'est pas un point d'atlas", () => {
    assert.deepEqual(atlasNoticeFromBody({ status: "unavailable" }), {
      unavailable: true,
      source: null,
      period: null,
    });
    assert.equal(atlasNoticeFromBody({ kind: "unavailable" }).unavailable, true);
  });

  it("garde la source et la période quand l'atlas répond", () => {
    const notice = atlasNoticeFromBody({
      kind: "climatology",
      period: "1993-2021",
      cyclone: { tracks_in_month: 4 },
    });
    assert.equal(notice.unavailable, false);
    assert.equal(notice.source, "IBTrACS");
    assert.equal(notice.period, "1993-2021");
  });
});

import { describe, it, test } from "node:test";
import assert from "node:assert/strict";
import fr from "../i18n/fr.js";
import en from "../i18n/en.js";
import { publicFilmReceipt, receiptLines, receiptModelKey, receiptModelRows } from "./filmReceipt.js";
import { resolveServedFilm } from "../hooks/useReplay.js";

const served = {
  hasWritten: true,
  source: "nemotron-super",
  receipt: {
    llmCalls: 9, cacheHits: 1, ruleFallbacks: 0,
    models: [
      { model: "nvidia/Nemotron-3.5-Super-VL", source: "nemotron-super", tier: "write", calls: 5, cached: 1 },
      { model: "nvidia/Nemotron-3-Ultra", source: "nemotron-ultra", tier: "deep", calls: 3 },
      { model: "nvidia/Nemotron-3-Ultra", source: "nemotron-ultra", tier: "judge", calls: 1 },
      { model: "x", source: "nemotron-super", tier: "write", calls: -2 },
    ],
    rewritten: 31, fallen: 2, super: 1, ultra_edit: 1, ultra_judge: 1, judgeFailed: 1,
    reviewed: true, reread: "pass", reread_en: "pass", lightning: 1,
    at: "2026-10-29T13:40:00Z", invented: "nope",
  },
};

describe("reçu « Comment ce film a été fait » (idée n° 3)", () => {
  it("ne garde que les compteurs servis, jamais un champ inconnu", () => {
    const r = publicFilmReceipt(served);
    assert.equal(r.llmCalls, 9);
    assert.equal(r.models.length, 3, "ligne à appels négatifs écartée");
    assert.equal(r.invented, undefined);
    assert.equal(publicFilmReceipt({ ...served, hasWritten: false }), null);
    assert.equal(publicFilmReceipt({ hasWritten: true }), null);
    assert.equal(publicFilmReceipt({ hasWritten: true, receipt: { models: [] } }), null);
  });

  it("regroupe les modèles par libellé Token Factory", () => {
    const rows = receiptModelRows(publicFilmReceipt(served));
    assert.deepEqual(rows.map((r) => [r.key, r.calls, r.cached]), [
      ["storySourceSuperVl", 5, 1],
      ["storySourceUltra", 4, 0],
    ]);
  });

  it("un repli NIM ne reçoit jamais le libellé Token Factory", () => {
    assert.equal(receiptModelKey({ source: "nvidia-nemotron-3-super", model: "nvidia/nemotron-3-super" }), "storySourceNim");
    assert.equal(receiptModelKey({ source: "nemotron-lightning", model: "nvidia/Nemotron-3.5-Lightning" }), "storySourceLightning");
  });

  it("étapes dans l'ordre réel, étape absente omise", () => {
    const keys = receiptLines(publicFilmReceipt(served), 3).map((l) => l.key);
    assert.deepEqual(keys, [
      "filmReceiptCalls", "filmReceiptRewritten", "filmReceiptJudgedPass",
      "filmReceiptRereadPass", "filmReceiptRereadEnPass", "filmReceiptTavily",
    ]);
    const bare = publicFilmReceipt({ hasWritten: true, receipt: { llmCalls: 2, models: [] } });
    assert.deepEqual(receiptLines(bare, 0).map((l) => l.key), ["filmReceiptCalls"]);
  });

  it("textes FR et EN présents pour chaque ligne", () => {
    for (const l of receiptLines(publicFilmReceipt(served), 2)) {
      assert.ok(fr[l.key] && en[l.key], l.key);
    }
    for (const k of ["filmReceiptTitle", "filmReceiptIntro", "filmReceiptModel", "filmReceiptModelCached", "filmReceiptAt", "filmReceiptFaults", "filmReceiptRuleFallbacks", "filmReceiptJudgedFail"]) {
      assert.ok(fr[k] && en[k], k);
    }
    assert.equal(en.filmReceiptTitle, "How this film was made");
    assert.equal(fr.filmReceiptTitle, "Comment ce film a été fait");
  });

  it("resolveServedFilm porte le reçu du rédigé seulement", () => {
    assert.equal(resolveServedFilm(served, "written").receipt.llmCalls, 9);
    assert.equal(resolveServedFilm(served, "raw").receipt, undefined);
  });
});

test("R45 : publicFilmReceipt ignore un webSourceCount serveur (avec ou sans)", () => {
  const base = { hasWritten: true, receipt: { llmCalls: 2 } };
  const without = publicFilmReceipt(base);
  const withCount = publicFilmReceipt({ hasWritten: true, receipt: { llmCalls: 2, webSourceCount: 10 } });
  assert.equal(without.webSourceCount, undefined);
  assert.equal(withCount.webSourceCount, undefined);
  assert.deepEqual(withCount, without);
});

test("R45 : la ligne Tavily du reçu suit le nombre de sources affichées", () => {
  const r = publicFilmReceipt({ hasWritten: true, receipt: { llmCalls: 2 } });
  assert.equal(receiptLines(r, 0).some((l) => l.key === "filmReceiptTavily"), false);
  const line = receiptLines(r, 2).find((l) => l.key === "filmReceiptTavily");
  assert.deepEqual(line.vars, { n: 2 });
});

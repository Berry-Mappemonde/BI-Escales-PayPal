import { describe, it } from "node:test";
import assert from "node:assert/strict";
import fr from "../i18n/fr.js";
import en from "../i18n/en.js";
import { describeTfLatency } from "./tfLatency.js";

const tr = (dict) => (key, vars = {}) => {
  const raw = dict[key];
  assert.equal(typeof raw, "string", `clé i18n manquante : ${key}`);
  return raw.replace(/\{(\w+)\}/g, (_, k) => (k in vars ? String(vars[k]) : `{${k}}`));
};

describe("describeTfLatency", () => {
  it("ne dit rien sans mesure", () => {
    assert.deepEqual(describeTfLatency(null, tr(en)), { latency: null, missing: [] });
    assert.deepEqual(describeTfLatency({ configuredModels: {} }, tr(en)), { latency: null, missing: [] });
  });

  it("donne la médiane par modèle, palier le plus appelé du groupe", () => {
    const llm = {
      latency: {
        nano: { lastMs: 400, medianMs: 450, calls: 2, samples: 2 },
        fast: { lastMs: 900, medianMs: 870, calls: 55, samples: 51 },
        write: { lastMs: 2100, medianMs: 2140, calls: 3, samples: 3 },
        judge: { lastMs: 6400, medianMs: 6380, calls: 1, samples: 1 },
      },
    };
    const en1 = describeTfLatency(llm, tr(en));
    assert.match(en1.latency, /Nemotron 3\.5 Lightning 0\.9 s/);
    assert.match(en1.latency, /Nemotron 3\.5 Super VL 2\.1 s/);
    assert.match(en1.latency, /Nemotron 3 Ultra 6\.4 s/);
    assert.match(en1.latency, /0\.9 s \(n=51\)/);
    const fr1 = describeTfLatency(llm, tr(fr));
    assert.match(fr1.latency, /Nemotron 3\.5 Lightning 0,9 s/);
  });

  it("annonce un modèle absent du catalogue et son remplaçant (jamais silencieux)", () => {
    const llm = {
      modelGuard: {
        missing: {
          write: { model: "nvidia/Nemotron-3.5-Super-VL", substitute: "nvidia/Nemotron-3_5-Lightning", substituteTier: "fast", count: 2 },
          deep: { model: "nvidia/Nemotron-3-Ultra-550b-a55b", substitute: null, count: 1 },
        },
      },
    };
    const res = describeTfLatency(llm, tr(en));
    assert.equal(res.missing.length, 2);
    assert.match(res.missing[0].text, /Nemotron 3\.5 Super VL.*Nemotron 3\.5 Lightning/);
    assert.match(res.missing[1].text, /Nemotron 3 Ultra/);
    const resFr = describeTfLatency(llm, tr(fr));
    assert.match(resFr.missing[0].text, /remplacé par Nemotron 3\.5 Lightning/);
  });

  it("ignore les lignes mal formées", () => {
    const res = describeTfLatency({ latency: { fast: { medianMs: "x", calls: 1, samples: 1 }, write: { medianMs: 10, calls: 0, samples: 0 } }, modelGuard: { missing: { write: {} } } }, tr(en));
    assert.deepEqual(res, { latency: null, missing: [] });
  });
});

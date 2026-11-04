// Visite « Qui fait quoi » : latence mesurée par le serveur (C1-a) et garde du
// catalogue Token Factory (C1-b), lues dans /ici/warm/status (`llm.latency`,
// `llm.modelGuard.missing`). Rien d'inventé : sans mesure, aucune ligne.
import { modelDisplayName, TOUR_DEFAULT_MODELS } from "../components/demoWalkthrough.js";

// Un nom par groupe de paliers (même modèle) ; on garde le palier le plus appelé.
const LATENCY_GROUPS = [
  ["nano", "fast"],
  ["write"],
  ["deep", "judge"],
];

function seconds(ms, decimal) {
  const s = (Math.max(0, Number(ms) || 0) / 1000).toFixed(1);
  return decimal && decimal !== "." ? s.replace(".", decimal) : s;
}

/**
 * @param {any} llm  bloc `llm` de /ici/warm/status (ou null)
 * @param {(key: string, vars?: object) => string} t
 * @returns {{ latency: string | null, missing: {tier: string, text: string}[] }}
 */
export function describeTfLatency(llm, t) {
  const out = { latency: null, missing: [] };
  if (!llm || typeof llm !== "object") return out;
  const models = { ...TOUR_DEFAULT_MODELS, ...(llm.configuredModels && typeof llm.configuredModels === "object" ? llm.configuredModels : {}) };
  const lat = llm.latency && typeof llm.latency === "object" ? llm.latency : {};
  const decimal = t("tfLatencyDecimal");
  const items = [];
  for (const tiers of LATENCY_GROUPS) {
    let best = null;
    for (const tier of tiers) {
      const row = lat[tier];
      const median = Number(row?.medianMs);
      const samples = Number(row?.samples) || 0;
      const calls = Number(row?.calls) || 0;
      if (!row || !Number.isFinite(median) || median < 0 || samples <= 0) continue;
      if (!best || calls > best.calls) best = { tier, median, calls, samples };
    }
    if (best) {
      items.push(t("tfLatencyItem", { model: modelDisplayName(models[best.tier]) || best.tier, s: seconds(best.median, decimal), n: String(best.samples) }));
    }
  }
  if (items.length) out.latency = t("tfLatencyLine", { list: items.join(" · ") });
  const missing = llm.modelGuard?.missing && typeof llm.modelGuard.missing === "object" ? llm.modelGuard.missing : {};
  for (const [tier, row] of Object.entries(missing)) {
    if (!row || typeof row !== "object" || !row.model) continue;
    const model = modelDisplayName(row.model);
    out.missing.push({
      tier,
      text: row.substitute
        ? t("tfModelMissingLine", { model, substitute: modelDisplayName(row.substitute) })
        : t("tfModelMissingNone", { model }),
    });
  }
  return out;
}

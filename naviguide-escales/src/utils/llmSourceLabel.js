/** Legacy film and story ids, including nemotron-super-token-factory. */
export function isLlmWrittenSource(source) {
  const s = String(source || "").toLowerCase();
  if (!s || s.endsWith("+local")) return false;
  if (s === "nemotron-super-token-factory" || s === "nemotron-super" || s === "nemotron") return true;
  if (s.endsWith("-lightning") || s.endsWith("-super") || s.endsWith("-ultra")) return true;
  if (s.includes("nemotron")) return true;
  return false;
}

/** True when the visible text was drafted by a language model. */
export function isAiGeneratedSource(source) {
  const s = String(source || "").trim().toLowerCase();
  if (!s || s.endsWith("+local") || s === "rules" || s === "budget") return false;
  if (s === "cache" || s === "openrouter" || s === "claude") return true;
  if (/gpt-oss|nvidia-gpt|\bnim\b|\bgpt-4o\b|\bgpt-4\b/i.test(s)) return true;
  return isLlmWrittenSource(source);
}

/** Super 120B (retired 9 Nov. 2026) only when the served model id names it explicitly. */
export function isLegacySuperModel(model) {
  const m = String(model || "").toLowerCase();
  return m.includes("super") && m.includes("120b");
}

/** i18n key from an exact Token Factory model id, or "" when the id is unknown. */
export function modelI18nKey(model) {
  const m = String(model || "").toLowerCase();
  if (!m) return "";
  if (m.includes("lightning")) return "storySourceLightning";
  if (m.includes("super-vl") || (m.includes("super") && m.includes("vl"))) return "storySourceSuperVl";
  if (isLegacySuperModel(m)) return "storySourceSuper120b";
  if (m.includes("nemotron") && m.includes("ultra")) return "storySourceUltra";
  if (m.includes("nemotron") && m.includes("nano")) return "storySourceNano";
  return "";
}

/** Map cascade `source` or an exact model id to an i18n key. `reviewedBy` names Ultra when it edited.
 * `model` (served model id, optional) wins over the tier source for the Super family.
 * The write tier serves Nemotron 3.5 Super VL (llm_budget.DEFAULT_MODELS) : a bare
 * « nemotron-super » source reads Super VL ; Super 120B only when `model` names it.
 * Token Factory labels are only the three Nemotron tiers; a fallback never receives one. */
export function llmSourceI18nKey(source, reviewedBy, model) {
  const s = String(source || "");
  const lower = s.toLowerCase();
  const reviewed = String(reviewedBy || "").toLowerCase();
  const legacy = isLegacySuperModel(model) || isLegacySuperModel(s);
  const ultraReviewed = reviewed.includes("ultra") && (lower.includes("nemotron") || lower.includes("super") || isLlmWrittenSource(s)) && (lower === "nemotron" || lower.includes("super"));
  if ((lower.includes("reviewed") && lower.includes("ultra")) || ultraReviewed) {
    return legacy ? "storySourceSuper120bReviewed" : "storySourceSuperReviewed";
  }
  if (s === "openrouter" || lower.startsWith("openrouter")) return "storySourceOpenrouter";
  if (s === "claude" || lower.startsWith("claude")) return "storySourceClaude";
  if (s === "rules") return "storySourceRules";
  if (s === "budget") return "storySourceBudget";
  if (s === "cache") return "storySourceCache";
  if (/gpt-oss|nvidia-gpt|\bnim\b/i.test(s) || lower.startsWith("nvidia-")) return "storySourceNim";
  if (/\bgpt-4o\b|\bgpt-4\b/i.test(lower)) return "storySourceOpenrouter";
  if (isLegacySuperModel(s)) return "storySourceSuper120b";
  if (lower.endsWith("-nano") || lower.includes("-nano")) return "storySourceNano";
  if (s.endsWith("-lightning") || lower.includes("lightning")) return "storySourceLightning";
  if (s.endsWith("-super-vl") || lower.includes("super-vl")) return "storySourceSuperVl";
  if (s.endsWith("-ultra") || (lower.includes("ultra") && lower.includes("nemotron"))) return "storySourceUltra";
  if (lower.endsWith("-super") || lower.includes("nemotron-3-super") || lower.includes("nemotron-super") || isLlmWrittenSource(s)) {
    if (legacy) return "storySourceSuper120b";
    const byModel = modelI18nKey(model);
    return byModel && byModel !== "storySourceNano" ? byModel : "storySourceSuper";
  }
  return "storySourceRules";
}

export function llmSourceLabel(source, t, reviewedBy, model) {
  return t(llmSourceI18nKey(source, reviewedBy, model));
}

const TOKEN_FACTORY_LABELS = new Set([
  "storySourceNano",
  "storySourceLightning",
  "storySourceSuper",
  "storySourceSuper120b",
  "storySourceSuperVl",
  "storySourceSuperReviewed",
  "storySourceSuper120bReviewed",
  "storySourceUltra",
]);

/** Nemotron on Token Factory — text names only, never a third-party logo. */
export function llmSourceShowsBrands(source) {
  return TOKEN_FACTORY_LABELS.has(llmSourceI18nKey(source));
}

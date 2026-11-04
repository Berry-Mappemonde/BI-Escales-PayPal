/**
 * Contrat minimal côté interface pour `expedition_plan`.
 * `briefing_title` est facultatif tant que l'orchestrateur ne le produit pas.
 */
export function normalizeExpeditionPlan(plan) {
  if (!plan || typeof plan !== "object") return null;
  const executiveBriefing = typeof plan.executive_briefing === "string"
    ? plan.executive_briefing.trim()
    : "";
  if (!executiveBriefing) return null;

  const briefingTitle = typeof plan.briefing_title === "string"
    ? plan.briefing_title.trim()
    : "";

  return {
    ...plan,
    executive_briefing: executiveBriefing,
    ...(briefingTitle ? { briefing_title: briefingTitle } : {}),
  };
}

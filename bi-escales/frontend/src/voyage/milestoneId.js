/**
 * Même repli que naviguide_bridge._slug : dep- + nom plié.
 * bi-escales/backend/app/escales/naviguide_bridge.py
 */
export function milestoneIdFromName(name) {
  const folded = String(name || "")
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .toLowerCase();
  const slug = folded.replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  return `dep-${slug || "escale"}`;
}

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

function foldStopName(name) {
  return String(name || "")
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .toLowerCase();
}

export function matchVoyageStop(stops, event) {
  const list = stops || [];
  const milestoneId = event?.milestoneId || "";
  const name = event?.name || "";
  const exact = list.find((item) => item.milestoneId === milestoneId || item.name === name);
  if (exact) return exact;
  const needle = foldStopName(name);
  if (needle.length < 4) return null;
  return list.find((item) => {
    const hay = foldStopName(item.name);
    return hay.includes(needle) || needle.includes(hay);
  }) || null;
}

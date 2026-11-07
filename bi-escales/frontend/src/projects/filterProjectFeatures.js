/**
 * Filtre liste / carte projets.
 * Copié de Berry-Mappemonde/Blue-Intelligence
 * `frontend/src/components/ProjectList.js` (l.6–10) et le même prédicat dans
 * `frontend/src/components/map/useProjectsLayer.js` (l.18–22),
 * commit 7dd7206a15a747a042b5e56c275775cc53061c98.
 */
export function filterProjectFeatures(
  features,
  { funderFilter = "All", categoryFilter = "All", searchQuery = "" } = {},
) {
  const q = (searchQuery || "").toLowerCase();
  return (features || []).filter(
    (f) => (funderFilter === "All" || (f.properties?.funder || "").includes(funderFilter))
      && (categoryFilter === "All" || f.properties?.category_group === categoryFilter)
      && (!q || `${f.properties?.title || ""} ${f.properties?.description || ""} ${f.properties?.funder || ""} ${f.properties?.location || ""} ${f.properties?.channel3_product_name || ""} ${f.properties?.project_kind || ""}`.toLowerCase().includes(q)),
  );
}

/** One Leaflet marker per milestone — route.geojson can repeat the same escale name. */
export function dedupeStopsByMilestone(stops) {
  const seen = new Set();
  return (stops || []).filter((stop) => {
    const key = String(stop?.milestoneId || stop?.name || "");
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

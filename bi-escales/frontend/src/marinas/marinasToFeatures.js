/**
 * Liste BI MarinasPanel : FeatureCollection de points.
 * Champs lus par MarinasPanel (name, id, osm_id, website) et
 * produits par escale_api._slim (name, lat, lon, nm, url).
 */
export function marinasToFeatures(fiche) {
  const items = fiche?.sections?.mooring?.marinas || [];
  return {
    type: "FeatureCollection",
    features: items
      .filter((item) => item && Number.isFinite(Number(item.lat)) && Number.isFinite(Number(item.lon)))
      .map((item, index) => ({
        type: "Feature",
        geometry: { type: "Point", coordinates: [Number(item.lon), Number(item.lat)] },
        properties: {
          id: String(item.osm_id || item.name || index),
          name: item.name,
          osm_id: item.osm_id || "",
          website: item.url || item.visit_url || "",
        },
      })),
  };
}

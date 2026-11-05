/**
 * Liste BI MarinasPanel : FeatureCollection de points.
 * Champs lus par MarinasPanel (name, id, osm_id, website) et
 * produits par escale_api._slim (name, lat, lon, nm, url).
 * Place-link guard: ``marinaPlaceLink.js`` (V3 ``marina_maps_place.py``).
 */
import { applyMarinaPlacePolicy } from "./marinaPlaceLink.js";

export function marinasToFeatures(fiche) {
  const items = fiche?.sections?.mooring?.marinas || [];
  return {
    type: "FeatureCollection",
    features: items
      .filter((item) => item && Number.isFinite(Number(item.lat)) && Number.isFinite(Number(item.lon)))
      .map((item, index) => {
        const row = applyMarinaPlacePolicy({
          ...item,
          maps_place_url: item.maps_place_url,
          maps_url: item.maps_url,
        });
        return {
          type: "Feature",
          geometry: { type: "Point", coordinates: [Number(row.lon), Number(row.lat)] },
          properties: {
            id: String(row.osm_id || row.name || index),
            name: row.name,
            osm_id: row.osm_id || "",
            website: row.url || row.visit_url || "",
            maps_url: row.maps_url || null,
            safe_google_place: Boolean(row.safe_google_place),
            nm: row.nm,
          },
        };
      }),
  };
}

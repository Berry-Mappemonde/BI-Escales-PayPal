import { useEffect, useRef } from "react";
import L from "leaflet";
import { worldCopyLineCoords } from "../utils/geo.js";

function addLine(group, coords, style) {
  if (!coords || coords.length < 2) return;
  worldCopyLineCoords(coords).forEach((copy) => {
    L.polyline(copy.map(([lon, lat]) => [lat, lon]), { ...style, pane: "route" }).addTo(group);
  });
}

/** Old searoute dashed, new track solid. Envelopes off. */
export function useAltRouteLayer(mapRef, { draft, showEnvelopes = false, mapReady }) {
  const groupRef = useRef(null);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return undefined;
    if (groupRef.current) groupRef.current.remove();
    if (!draft) return undefined;
    const group = L.layerGroup().addTo(map);
    groupRef.current = group;
    const oldC = draft.old_geojson?.geometry?.coordinates;
    const neu = draft.draft_geojson?.geometry?.coordinates;
    if (oldC) addLine(group, oldC, { color: "#94a3b8", weight: 2, dashArray: "7 7", opacity: 0.85 });
    if (neu) addLine(group, neu, { color: "#22d3ee", weight: 3, opacity: 0.95 });
    if (showEnvelopes && draft.isochrones?.length) {
      draft.isochrones.forEach((iso) => {
        const ring = (iso || []).map((p) => [p.lon, p.lat]);
        if (ring.length > 2) addLine(group, ring, { color: "#fbbf24", weight: 1, dashArray: "2 4", opacity: 0.4 });
      });
    }
    return () => group.remove();
  }, [mapRef, mapReady, draft, showEnvelopes]);

  return groupRef;
}

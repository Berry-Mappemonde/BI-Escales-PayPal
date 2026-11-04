import { useEffect, useRef } from "react";
import L from "leaflet";
import { worldCopyLineCoords } from "../utils/geo.js";

/** Dashed air-hop line, only while the plane is in the air. */
export function useAirHopLine(mapRef, { mapReady, visible, from, to }) {
  const groupRef = useRef(null);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady || !visible || !from || !to) {
      groupRef.current?.remove();
      groupRef.current = null;
      return undefined;
    }
    groupRef.current?.remove();
    const group = L.layerGroup().addTo(map);
    worldCopyLineCoords([
      [from.lon, from.lat],
      [to.lon, to.lat],
    ]).forEach((copy) => {
      L.polyline(copy.map(([lon, lat]) => [lat, lon]), {
        color: "#67e8f9",
        weight: 2,
        dashArray: "7 9",
        opacity: 0.8,
        pane: "route",
        interactive: false,
      }).addTo(group);
    });
    groupRef.current = group;
    return undefined;
  }, [mapRef, mapReady, visible, from?.lat, from?.lon, to?.lat, to?.lon]);

  useEffect(() => () => {
    groupRef.current?.remove();
    groupRef.current = null;
  }, []);
}

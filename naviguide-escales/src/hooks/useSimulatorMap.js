import { useEffect, useRef, useState } from "react";
import L from "leaflet";
import { TILE_ATTRIBUTION, TILE_URLS } from "../layers/styles.js";
import { createPanes } from "../layers/layerOrder.js";

export function useSimulatorMap(containerRef, isLightMode) {
  const mapRef = useRef(null);
  const baseRef = useRef(null);
  const [mapReady, setMapReady] = useState(0);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return undefined;
    const map = L.map(containerRef.current, {
      center: [22, 5],
      zoom: 2,
      zoomSnap: 0.25,
      minZoom: 2,
      maxZoom: 18,
      worldCopyJump: false,
    });
    createPanes(map);
    const base = L.tileLayer(TILE_URLS.dark, {
      attribution: TILE_ATTRIBUTION,
    }).addTo(map);
    baseRef.current = base;
    mapRef.current = map;
    setMapReady((n) => n + 1);
    const raf = requestAnimationFrame(() => {
      if (mapRef.current === map) map.invalidateSize();
    });
    return () => {
      cancelAnimationFrame(raf);
      map.remove();
      mapRef.current = null;
      baseRef.current = null;
      setMapReady(0);
    };
  }, [containerRef]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;
    const url = isLightMode ? TILE_URLS.light : TILE_URLS.dark;
    if (baseRef.current) {
      map.removeLayer(baseRef.current);
    }
    baseRef.current = L.tileLayer(url, { attribution: TILE_ATTRIBUTION }).addTo(map);
    baseRef.current.bringToBack();
  }, [isLightMode, mapReady]);

  return { mapRef, mapReady };
}

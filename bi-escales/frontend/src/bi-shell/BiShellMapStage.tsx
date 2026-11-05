import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import type { ReactNode } from "react";

type Props = {
  popup?: ReactNode;
};

/** Empty world map stage (Leaflet) — Escalés MapScene can replace via slots.map. */
export function BiShellMapStage({ popup }: Props) {
  const ref = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<L.Map | null>(null);

  useEffect(() => {
    if (!ref.current || mapRef.current) return;
    const map = L.map(ref.current, {
      center: [20, -30],
      zoom: 2,
      worldCopyJump: true,
      zoomControl: true,
    });
    L.tileLayer(
      "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}",
      {
        attribution: "Tiles &copy; Esri",
        maxZoom: 16,
      },
    ).addTo(map);
    // Placeholder marina dots (empty shell demo markers — not live Escales data)
    const demo = L.layerGroup().addTo(map);
    for (const [lat, lon] of [
      [46.15, -1.15],
      [14.6, -61.07],
      [-17.53, -149.57],
      [48.39, -4.49],
    ] as const) {
      L.circleMarker([lat, lon], {
        radius: 5,
        color: "#0f172a",
        weight: 1,
        fillColor: "#ff4a4a",
        fillOpacity: 0.9,
      }).addTo(demo);
    }
    mapRef.current = map;
    requestAnimationFrame(() => map.invalidateSize());
    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  return (
    <div className="bi-shell-map" data-testid="bi-shell-map">
      <div ref={ref} style={{ width: "100%", height: "100%" }} />
      {popup ? (
        <div
          className="bi-popup-card"
          data-testid="bi-shell-popup"
          style={{ position: "absolute", left: "50%", top: "20%", transform: "translateX(-50%)", zIndex: 500 }}
        >
          {popup}
        </div>
      ) : (
        <div
          className="bi-popup-card"
          data-testid="bi-shell-popup-template"
          style={{ position: "absolute", left: "1rem", bottom: "1rem", zIndex: 500, opacity: 0.92 }}
        >
          <p className="bi-slot-label">popup (BI format)</p>
          <p className="bi-slot-empty">Empty card template — Escalés EscalePopup / MarinaMapPopup / ProjectMapPopup</p>
        </div>
      )}
    </div>
  );
}

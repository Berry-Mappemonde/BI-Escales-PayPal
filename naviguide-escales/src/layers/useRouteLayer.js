import { useEffect, useRef } from "react";
import L from "leaflet";
import { useLang } from "../i18n/LangContext.jsx";
import { worldCopyLineCoords } from "../utils/geo.js";
import { ROUTE_CASING_COLOR, ROUTE_CASING_WEIGHT, ROUTE_MAIN_COLOR, ROUTE_MAIN_WEIGHT } from "./styles.js";
import { REGIME_COLORS, traveledEraSpeed, traveledRegimeSegments } from "./regimeRoute.js";

export { REGIME_COLORS, traveledEraSpeed, traveledRegimeSegments };

function addLine(group, coords, { color, weight, dash, pane = "route", tooltip = null }) {
  if (!coords || coords.length < 2) return;
  worldCopyLineCoords(coords).forEach((copy) => {
    const latlngs = copy.map(([lon, lat]) => [lat, lon]);
    const line = L.polyline(latlngs, {
      color,
      weight,
      dashArray: dash,
      pane,
      interactive: true,
    });
    if (tooltip) {
      line.bindTooltip(tooltip, {
        sticky: true,
        direction: "top",
        opacity: 0.95,
        className: "traveled-era-speed",
      });
    }
    line.addTo(group);
  });
}

export function useRouteLayer(mapRef, {
  segments,
  customRoute,
  drawingMode,
  drawnSegments,
  drawnFailed,
  mapReady,
  visible = true,
  hideMaritime = false,
  paintMain = true,
  clockVertices = null,
  traveledNm = null,
}) {
  const { t } = useLang();
  const groupRef = useRef(null);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return undefined;
    if (groupRef.current) groupRef.current.remove();
    const group = L.layerGroup().addTo(map);
    groupRef.current = group;

    if (drawingMode) {
      drawnSegments.filter(Boolean).forEach((s) => {
        addLine(group, s.coords, {
          color: "#22c55e",
          weight: 3,
        });
      });
      return () => group.remove();
    }

    if (paintMain && visible) {
      if (customRoute?.features) {
        customRoute.features
          .filter((f) => f.geometry?.type === "LineString")
          .forEach((f) => {
            addLine(group, f.geometry.coordinates, { color: "#0077ff", weight: ROUTE_MAIN_WEIGHT });
          });
      } else {
        (segments || []).forEach((s) => {
          if (!s.coords?.length) return;
          if (s.nonMaritime) {
            addLine(group, s.coords, { color: "orange", weight: 4, dash: "6 6" });
          } else if (!hideMaritime) {
            addLine(group, s.coords, { color: ROUTE_CASING_COLOR, weight: ROUTE_CASING_WEIGHT });
            addLine(group, s.coords, { color: "#0077ff", weight: ROUTE_MAIN_WEIGHT });
          }
        });
      }
    }

    if (visible && clockVertices?.length && Number(traveledNm) > 0) {
      traveledRegimeSegments(clockVertices, traveledNm).forEach((s) => {
        const knots = traveledEraSpeed(s);
        const tooltip = knots == null
          ? null
          : `<span data-testid="traveled-era-speed">${t("traveledEraSpeed", { knots: knots.toFixed(1) })}</span>`;
        addLine(group, s.coords, {
          color: REGIME_COLORS[s.regime] || REGIME_COLORS.climatology,
          weight: 5,
          tooltip,
        });
      });
    }

    return () => group.remove();
  }, [
    mapRef, mapReady, segments, customRoute, drawingMode, drawnSegments, drawnFailed,
    visible, hideMaritime, paintMain, clockVertices, traveledNm, t,
  ]);

  return groupRef;
}

export { ROUTE_MAIN_COLOR };

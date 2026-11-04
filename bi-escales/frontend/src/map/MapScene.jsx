/**
 * Carte Leaflet du mini-mix.
 * Extrait de naviguide-escales/src/map/MapScene.jsx (montage) et
 * MapSceneController.mount / syncRoute / syncWaypoints, plus le trait
 * maritime de layers/useRouteLayer.js. Pas de film, replay, GRIB,
 * climatologie, dessin, ni des hooks MapLibre de Blue Intelligence.
 * Les couches passent par SceneLayerRegistry.js.
 */
import { useEffect, useRef } from "react";
import { createRoot } from "react-dom/client";
import { I18nextProvider } from "react-i18next";
import { useTranslation } from "react-i18next";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import i18n from "../i18n";
import { ProjectMapPopup } from "../components/ProjectMapPopup.jsx";
import { SceneLayerRegistry } from "../../../../naviguide-escales/src/map/SceneLayerRegistry.js";
import { createPanes } from "../../../../naviguide-escales/src/layers/layerOrder.js";
import {
  FALLBACK_COLORS,
  ROUTE_CASING_COLOR,
  ROUTE_CASING_WEIGHT,
  ROUTE_MAIN_WEIGHT,
  tileAttribution,
} from "../../../../naviguide-escales/src/layers/styles.js";
import { worldCopyLineCoords } from "../../../../naviguide-escales/src/utils/geo.js";
import { officialAirRouteStyles } from "../../../../naviguide-escales/src/utils/berryLegs.js";
import { catamaranSvg } from "../../../../naviguide-escales/src/engine/catamaranIcon.js";
import { drawingPinHtml } from "../../../../naviguide-escales/src/utils/waypointFlags.js";
import { applyMarkerRotation } from "../../../../naviguide-escales/src/utils/markerRotation.js";
import { mapTileUrlForTheme } from "./mapTileUrl.js";

const WORLD_CENTER = [22, 5];

function addRouteLine(group, coords, { color, weight, dash }) {
  if (!coords || coords.length < 2) return;
  worldCopyLineCoords(coords).forEach((copy) => {
    L.polyline(copy.map(([lon, lat]) => [lat, lon]), {
      color,
      weight,
      dashArray: dash,
      pane: "route",
      interactive: false,
    }).addTo(group);
  });
}

function paintSegment(group, segment) {
  const styles = officialAirRouteStyles(segment);
  if (styles.length) {
    styles.forEach((style) => addRouteLine(group, segment.coords, style));
    return;
  }
  if (segment.nonMaritime) {
    addRouteLine(group, segment.coords, { color: "orange", weight: 4, dash: "6 6" });
    return;
  }
  addRouteLine(group, segment.coords, { color: ROUTE_CASING_COLOR, weight: ROUTE_CASING_WEIGHT });
  addRouteLine(group, segment.coords, { color: "#0077ff", weight: ROUTE_MAIN_WEIGHT });
}

export function MapScene({
  segments,
  stops,
  boat,
  projects,
  marinas,
  showProjects,
  showMarinas,
  flyTo,
  onSelectStop,
  onSelectProject,
  onFlyTo,
  contributor = "",
  onPledgeAuthorized,
  theme = "dark",
}) {
  const { i18n: i18nInstance } = useTranslation();
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const baseLayerRef = useRef(null);
  const layersRef = useRef(null);
  const onSelectRef = useRef(onSelectStop);
  onSelectRef.current = onSelectStop;
  const onProjectRef = useRef(onSelectProject);
  onProjectRef.current = onSelectProject;
  const onFlyToRef = useRef(onFlyTo);
  onFlyToRef.current = onFlyTo;
  const contributorRef = useRef(contributor);
  contributorRef.current = contributor;
  const onPledgeAuthorizedRef = useRef(onPledgeAuthorized);
  onPledgeAuthorizedRef.current = onPledgeAuthorized;
  const popupRootsRef = useRef(new Map());

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return undefined;
    const map = L.map(containerRef.current, {
      center: WORLD_CENTER,
      zoom: 2,
      zoomSnap: 0.25,
      minZoom: 2,
      maxZoom: 12,
      worldCopyJump: false,
    });
    const tileLayer = L.tileLayer(mapTileUrlForTheme(theme), {
      attribution: tileAttribution(i18nInstance.language),
    }).addTo(map);
    baseLayerRef.current = tileLayer;
    createPanes(map);
    mapRef.current = map;
    layersRef.current = new SceneLayerRegistry();
    return () => {
      layersRef.current?.clear();
      map.remove();
      mapRef.current = null;
      layersRef.current = null;
      baseLayerRef.current = null;
    };
  }, []);

  useEffect(() => {
    const layer = baseLayerRef.current;
    if (!layer || typeof layer.setUrl !== "function") return;
    layer.setUrl(mapTileUrlForTheme(theme));
  }, [theme]);

  useEffect(() => {
    const map = mapRef.current;
    const layers = layersRef.current;
    if (!map || !layers) return;
    const group = layers.update("route", () => L.layerGroup().addTo(map), (layer) => layer.clearLayers());
    const bounds = [];
    (segments || []).forEach((segment) => {
      paintSegment(group, segment);
      (segment.coords || []).forEach(([lon, lat]) => bounds.push([lat, lon]));
    });
    if (bounds.length) map.fitBounds(bounds, { padding: [24, 24] });
  }, [segments]);

  useEffect(() => {
    const map = mapRef.current;
    const layers = layersRef.current;
    if (!map || !layers) return;
    const group = layers.update("stops", () => L.layerGroup().addTo(map), (layer) => layer.clearLayers());
    (stops || []).forEach((stop) => {
      const srcs = stop.flags || [];
      const html = srcs.length
        ? `<div class="flag-stack">${srcs.map((src) => `<img src="${src}" alt="" style="height:22px;width:auto;display:block" />`).join("")}</div>`
        : drawingPinHtml(0);
      const icon = L.divIcon({
        className: "flag-divicon",
        html,
        iconSize: srcs.length ? [22 * srcs.length, 24] : [14, 14],
        iconAnchor: srcs.length ? [11 * srcs.length, 12] : [7, 7],
      });
      const marker = L.marker([stop.lat, stop.lon], { icon, pane: "markerPane" }).addTo(group);
      marker.bindTooltip(stop.name, { direction: "top" });
      marker.on("click", (event) => {
        L.DomEvent.stopPropagation(event);
        onSelectRef.current?.(stop);
      });
    });
  }, [stops]);

  useEffect(() => {
    const map = mapRef.current;
    const layers = layersRef.current;
    if (!map || !layers) return;
    const group = layers.update("boat", () => L.layerGroup().addTo(map), (layer) => layer.clearLayers());
    if (!boat || !Number.isFinite(boat.lat) || !Number.isFinite(boat.lon)) return;
    const marker = L.marker([boat.lat, boat.lon], {
      icon: L.divIcon({
        className: "boat-divicon",
        html: catamaranSvg(boat.bearing || 0),
        iconSize: [64, 64],
        iconAnchor: [32, 32],
      }),
      pane: "boat",
      interactive: false,
    }).addTo(group);
    applyMarkerRotation(marker, boat.bearing || 0);
  }, [boat]);

  useEffect(() => {
    const map = mapRef.current;
    const layers = layersRef.current;
    if (!map || !layers) return undefined;
    const group = layers.update("projects", () => L.layerGroup().addTo(map), (layer) => layer.clearLayers());
    const roots = popupRootsRef.current;
    roots.forEach((root) => root.unmount());
    roots.clear();
    if (!showProjects) return undefined;
    (projects?.features || []).forEach((feature) => {
      const [lon, lat] = feature.geometry?.coordinates || [];
      if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;
      const groupName = feature.properties?.category_group;
      const color = FALLBACK_COLORS[groupName] || FALLBACK_COLORS.Other;
      const marker = L.circleMarker([lat, lon], {
        radius: 4,
        color,
        weight: 1,
        fillColor: color,
        fillOpacity: 0.85,
        pane: "overlayPane",
      }).addTo(group);
      if (feature.properties?.title) marker.bindTooltip(feature.properties.title, { direction: "top" });
      const popupContainer = document.createElement("div");
      popupContainer.className = "project-map-popup";
      let popupRoot = null;

      const mountPopup = () => {
        popupRoot?.unmount();
        popupRoot = createRoot(popupContainer);
        roots.set(marker, popupRoot);
        popupRoot.render(
          <I18nextProvider i18n={i18n}>
            <ProjectMapPopup
              properties={feature.properties}
              contributorDefault={contributorRef.current}
              onAuthorized={(pledge) => onPledgeAuthorizedRef.current?.(pledge)}
            />
          </I18nextProvider>,
        );
      };

      marker.bindPopup(popupContainer, {
        maxWidth: 360,
        minWidth: 260,
        className: "ng-project-leaflet-popup",
        autoPan: true,
        keepInView: true,
      });
      marker.on("popupopen", mountPopup);
      marker.on("popupclose", () => {
        popupRoot?.unmount();
        popupRoot = null;
        roots.delete(marker);
      });
      marker.on("click", (event) => {
        L.DomEvent.stopPropagation(event);
        const props = feature.properties || {};
        onFlyToRef.current?.(props.id, lat, lon);
        onProjectRef.current?.(props);
        marker.openPopup();
      });
    });
    return () => {
      roots.forEach((root) => root.unmount());
      roots.clear();
    };
  }, [projects, showProjects, contributor, onPledgeAuthorized, i18nInstance.language]);

  useEffect(() => {
    const map = mapRef.current;
    const layers = layersRef.current;
    if (!map || !layers) return;
    const group = layers.update("marinas", () => L.layerGroup().addTo(map), (layer) => layer.clearLayers());
    if (!showMarinas) return;
    (marinas?.features || []).forEach((feature) => {
      const [lon, lat] = feature.geometry?.coordinates || [];
      if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;
      const marker = L.circleMarker([lat, lon], {
        radius: 5,
        color: "#ff4a4a",
        weight: 1,
        fillColor: "#ff4a4a",
        fillOpacity: 0.8,
      }).addTo(group);
      if (feature.properties?.name) marker.bindTooltip(feature.properties.name, { direction: "top" });
    });
  }, [marinas, showMarinas]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !flyTo || !Number.isFinite(flyTo.lat) || !Number.isFinite(flyTo.lon)) return;
    map.setView([flyTo.lat, flyTo.lon], Math.max(map.getZoom(), 8), { animate: true });
  }, [flyTo]);

  return <div ref={containerRef} className="voyage-map" data-testid="voyage-map" />;
}

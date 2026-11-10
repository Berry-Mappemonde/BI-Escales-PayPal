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
import { MarinaMapPopup } from "../components/MarinaMapPopup.jsx";
import { SceneLayerRegistry } from "../../../../naviguide-escales/src/map/SceneLayerRegistry.js";
import { createPanes } from "../../../../naviguide-escales/src/layers/layerOrder.js";
import {
  ROUTE_CASING_COLOR,
  ROUTE_CASING_WEIGHT,
  ROUTE_MAIN_WEIGHT,
  tileAttribution,
} from "../../../../naviguide-escales/src/layers/styles.js";
import { worldCopyLineCoords } from "../../../../naviguide-escales/src/utils/geo.js";
import { officialAirRouteStyles } from "../../../../naviguide-escales/src/utils/berryLegs.js";
import { catamaranSvg } from "../../../../naviguide-escales/src/engine/catamaranIcon.js";
import { escapeAttr, stopMarkerIconHtml, stopMarkerIconSize } from "./stopMarkerIcon.js";
import { applyMarkerRotation } from "../../../../naviguide-escales/src/utils/markerRotation.js";
import { mapTileUrlForTheme } from "./mapTileUrl.js";
import { dedupeStopsByMilestone } from "../voyage/stopsForMap.js";
import {
  BOAT_ANCHOR,
  BOAT_ICON,
  boatMarkerAnchorOffset,
  computeStopOffsets,
  offsetToIconAnchor,
} from "./stopMarkerLayout.js";

/** Leaflet makes a marker a focusable button; this gives that button its name. */
function nameMarker(marker, label) {
  const element = marker.getElement?.();
  if (element && label) element.setAttribute("aria-label", label);
}

const WORLD_CENTER = [22, 5];

/**
 * The two optional layers get their own panes under the route (380) and the stop
 * flags (600), so the voyage stays readable with both switched on. Marinas sit
 * above projects: there are fewer of them and each belongs to a stop.
 */
export const LAYER_PANES = { projects: "bi-projects", marinas: "bi-marinas" };
const LAYER_PANE_Z = { [LAYER_PANES.projects]: 372, [LAYER_PANES.marinas]: 376 };

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
  onSelectBoat,
  onSelectProject,
  onFlyTo,
  contributor = "",
  onPledgeAuthorized,
  marinaMilestoneId = "",
  theme = "dark",
}) {
  const { i18n: i18nInstance, t } = useTranslation();
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const baseLayerRef = useRef(null);
  const layersRef = useRef(null);
  const onSelectRef = useRef(onSelectStop);
  onSelectRef.current = onSelectStop;
  const onSelectBoatRef = useRef(onSelectBoat);
  onSelectBoatRef.current = onSelectBoat;
  const onProjectRef = useRef(onSelectProject);
  onProjectRef.current = onSelectProject;
  const onFlyToRef = useRef(onFlyTo);
  onFlyToRef.current = onFlyTo;
  const contributorRef = useRef(contributor);
  contributorRef.current = contributor;
  const onPledgeAuthorizedRef = useRef(onPledgeAuthorized);
  onPledgeAuthorizedRef.current = onPledgeAuthorized;
  const popupRootsRef = useRef(new Map());
  const stopOffsetsRef = useRef([]);

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
    Object.entries(LAYER_PANE_Z).forEach(([name, zIndex]) => {
      map.createPane(name).style.zIndex = String(zIndex);
    });
    mapRef.current = map;
    layersRef.current = new SceneLayerRegistry();
    // Hard reload can mount before layout; force Leaflet to measure the pane.
    requestAnimationFrame(() => {
      try {
        map.invalidateSize(false);
      } catch {
        /* map already removed */
      }
    });
    // Changing a desktop rail resizes the map without a window resize event.
    const resize = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(() => map.invalidateSize(false));
    resize?.observe(containerRef.current);
    return () => {
      resize?.disconnect();
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
    if (!map || !layers) return undefined;

    const uniqueStops = dedupeStopsByMilestone(stops);
    const group = layers.update("stops", () => L.layerGroup().addTo(map), (layer) => layer.clearLayers());

    const renderStops = () => {
      group.clearLayers();
      const project = (lon, lat) => {
        const point = map.latLngToLayerPoint([lat, lon]);
        return { x: point.x, y: point.y };
      };
      const offsets = computeStopOffsets(uniqueStops, segments, project, stopOffsetsRef.current);
      stopOffsetsRef.current = offsets;

      uniqueStops.forEach((stop, index) => {
        const { iconSize, iconAnchor } = stopMarkerIconSize(stop);
        const anchor = offsetToIconAnchor(iconAnchor, offsets[index] || [0, 0]);
        const icon = L.divIcon({
          className: "flag-divicon",
          html: stopMarkerIconHtml(stop),
          iconSize,
          iconAnchor: anchor,
        });
        const marker = L.marker([stop.lat, stop.lon], {
          icon,
          pane: "markerPane",
          stopData: stop,
        }).addTo(group);
        marker.bindTooltip(stop.name, { direction: "top" });
        nameMarker(marker, t("map.stopMarker", { name: stop.name }));
        marker.on("click", (event) => {
          L.DomEvent.stopPropagation(event);
          const target = event?.target?.options?.stopData || stop;
          onSelectRef.current?.(target);
        });
      });
    };

    renderStops();
    map.on("zoomend", renderStops);
    map.on("moveend", renderStops);
    return () => {
      map.off("zoomend", renderStops);
      map.off("moveend", renderStops);
    };
  }, [stops, segments, i18nInstance.language, t]);

  useEffect(() => {
    const map = mapRef.current;
    const layers = layersRef.current;
    if (!map || !layers) return undefined;

    const uniqueStops = dedupeStopsByMilestone(stops);
    const group = layers.update("boat", () => L.layerGroup().addTo(map), (layer) => layer.clearLayers());
    if (!boat || !Number.isFinite(boat.lat) || !Number.isFinite(boat.lon)) return undefined;

    const boatLabel = t("map.boatMarker");

    const renderBoat = () => {
      group.clearLayers();
      const project = (lon, lat) => {
        const point = map.latLngToLayerPoint([lat, lon]);
        return { x: point.x, y: point.y };
      };
      const offsets = stopOffsetsRef.current.length
        ? stopOffsetsRef.current
        : computeStopOffsets(uniqueStops, segments, project, []);
      const boatOffset = boatMarkerAnchorOffset(boat, uniqueStops, offsets, project);
      const iconAnchor = offsetToIconAnchor(BOAT_ANCHOR, boatOffset);
      const marker = L.marker([boat.lat, boat.lon], {
        icon: L.divIcon({
          className: "boat-divicon",
          html: `<div role="img" aria-label="${escapeAttr(boatLabel)}">${catamaranSvg(boat.bearing || 0, { size: BOAT_ICON })}</div>`,
          iconSize: [BOAT_ICON, BOAT_ICON],
          iconAnchor,
        }),
        pane: "boat",
        interactive: true,
        riseOnHover: true,
        zIndexOffset: 1200,
      }).addTo(group);
      applyMarkerRotation(marker, boat.bearing || 0);
      nameMarker(marker, boatLabel);
      marker.on("click", (event) => {
        L.DomEvent.stopPropagation(event);
        onSelectBoatRef.current?.();
      });
    };

    renderBoat();
    map.on("zoomend", renderBoat);
    map.on("moveend", renderBoat);
    return () => {
      map.off("zoomend", renderBoat);
      map.off("moveend", renderBoat);
    };
  }, [boat, stops, segments, i18nInstance.language, t]);

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
      // One neutral tone for every project, set by .project-dot from the tokens: the
      // dots are context for the voyage, and must stay quieter than the route.
      const marker = L.circleMarker([lat, lon], {
        radius: 2,
        stroke: false,
        fillColor: "currentColor",
        fillOpacity: 1,
        className: "project-dot",
        pane: LAYER_PANES.projects,
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
    const roots = new Map();
    (marinas?.features || []).forEach((feature) => {
      const [lon, lat] = feature.geometry?.coordinates || [];
      if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;
      const props = feature.properties || {};
      const verified = Boolean(props.safe_google_place);
      const rejected = Boolean(props.maps_place_rejected);
      // Colours come from the marina tokens through .marina-dot, the same ones the legend uses.
      const marker = L.circleMarker([lat, lon], {
        radius: 4,
        color: "currentColor",
        weight: rejected && !verified ? 2 : 1,
        fillColor: "currentColor",
        fillOpacity: 0.85,
        className: `marina-dot${verified ? " marina-dot--verified" : ""}`,
        pane: LAYER_PANES.marinas,
      }).addTo(group);
      if (props.name) marker.bindTooltip(props.name, { direction: "top" });
      const container = document.createElement("div");
      let popupRoot = null;
      const mountPopup = () => {
        popupRoot?.unmount();
        popupRoot = createRoot(container);
        popupRoot.render(
          <I18nextProvider i18n={i18n}>
            <MarinaMapPopup
              properties={props}
              milestoneId={marinaMilestoneId}
              contributorDefault={contributor}
              onAuthorized={onPledgeAuthorized}
            />
          </I18nextProvider>,
        );
      };
      marker.bindPopup(container, { maxWidth: 320, autoPan: true, keepInView: true });
      marker.on("popupopen", mountPopup);
      marker.on("popupclose", () => {
        popupRoot?.unmount();
        popupRoot = null;
      });
      marker.on("click", (event) => {
        L.DomEvent.stopPropagation(event);
        onFlyToRef.current?.(props.id, lat, lon);
        marker.openPopup();
      });
      roots.set(marker, popupRoot);
    });
    return () => {
      roots.forEach((root) => root?.unmount());
      roots.clear();
    };
  }, [marinas, showMarinas, contributor, onPledgeAuthorized, marinaMilestoneId, i18nInstance.language]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !flyTo || !Number.isFinite(flyTo.lat) || !Number.isFinite(flyTo.lon)) return;
    map.setView([flyTo.lat, flyTo.lon], Math.max(map.getZoom(), 8), { animate: true });
  }, [flyTo]);

  return <div ref={containerRef} className="voyage-map" data-testid="voyage-map" />;
}

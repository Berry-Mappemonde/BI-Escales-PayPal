import { useEffect, useRef, useState } from "react";
import L from "leaflet";
import { featuresToSegments, wrapLon } from "../utils/geo.js";
import { useToggleLayers } from "../layers/useToggleLayers.js";
import { useClimatologyLayer } from "../layers/useClimatologyLayer.js";
import { useGribCorridorLayer } from "../layers/useGribCorridorLayer.js";
import { useRouteLayer } from "../layers/useRouteLayer.js";
import { useWeatherPipeline } from "../hooks/useWeatherPipeline.js";
import { MapSceneController } from "./MapSceneController.js";
import { isNearRoute } from "./routeClick.js";

/**
 * React boundary for the map. Its controller owns all mobile Leaflet objects;
 * the root only receives commands and a HUD snapshot at a bounded cadence.
 */
export function MapScene({
  scene,
  gateRef,
  onReady,
  onPlayback,
  onLayerState,
  onClimatologyState,
  onFeature,
  onCameraPlaced,
  onManualNavigation,
  onDrawingClick,
  onRouteClick,
  onBoatDrag,
  onCoordinatesCopied,
  onWaypointHover,
  onDrawingWaypointClick,
  onWaypointClick,
}) {
  const containerRef = useRef(null);
  const controllerRef = useRef(null);
  const mapRef = useRef(null);
  const [mapReady, setMapReady] = useState(0);
  const callbacksRef = useRef({});
  callbacksRef.current = {
    onReady,
    onPlayback,
    onCameraPlaced,
    onManualNavigation,
    onDrawingClick,
    onRouteClick,
    onBoatDrag,
    onCoordinatesCopied,
    onWaypointHover,
    onDrawingWaypointClick,
    onWaypointClick,
  };

  useEffect(() => {
    if (!containerRef.current) return undefined;
    const controller = MapSceneController.mount(containerRef.current, {
      onPlayback: (snapshot) => callbacksRef.current.onPlayback?.(snapshot),
      onCameraPlaced: (placed) => callbacksRef.current.onCameraPlaced?.(placed),
      onManualNavigation: () => callbacksRef.current.onManualNavigation?.(),
      onBoatDrag: (position) => callbacksRef.current.onBoatDrag?.(position),
      onWaypointHover: (point) => callbacksRef.current.onWaypointHover?.(point),
      onDrawingWaypointClick: (point, index) => callbacksRef.current.onDrawingWaypointClick?.(point, index),
      onWaypointClick: (point, index) => callbacksRef.current.onWaypointClick?.(point, index),
    });
    controllerRef.current = controller;
    mapRef.current = controller.map;
    // Recette / e2e : le contrôleur de scène est exposé (zoom, carte).
    if (typeof window !== "undefined") window.__naviguideScene = controller;
    // La capture du film attend ce marqueur : la carte a sa première vue.
    const markAppReady = () => {
      containerRef.current?.setAttribute("data-testid", "app-ready");
    };
    if (typeof controller.map?.whenReady === "function") controller.map.whenReady(markAppReady);
    else markAppReady();
    setMapReady(1);
    callbacksRef.current.onReady?.(controller.api);
    return () => {
      containerRef.current?.removeAttribute("data-testid");
      callbacksRef.current.onReady?.(null);
      if (typeof window !== "undefined" && window.__naviguideScene === controller) {
        delete window.__naviguideScene;
      }
      controller.dispose();
      controllerRef.current = null;
      mapRef.current = null;
    };
  }, []);

  const maritimeLayers = useToggleLayers(mapRef, onFeature, mapReady, gateRef, {
    cameraFollowing: scene.cameraFollow,
  });
  const climoLayer = useClimatologyLayer({
    mapRef,
    mapReady,
    showWind: maritimeLayers.showClimoWind,
    showWave: maritimeLayers.showClimoWave,
    showCurrent: maritimeLayers.showClimoCurrent,
    showCyclones: maritimeLayers.showClimoCyclones,
    month: scene.climoMonth,
    drawing: scene.drawingMode,
    t: scene.t,
  });
  const weather = useWeatherPipeline({ grib: scene.grib, climatology: climoLayer });
  const gribCorridorReady = weather.layers.gribWind === "ready";

  useGribCorridorLayer(mapRef, {
    grib: scene.grib,
    mapReady,
    visible: maritimeLayers.showGrib && scene.isSuivre && gribCorridorReady,
    whenIso: scene.clockSample?.iso,
    lat: scene.isSuivre ? scene.live?.lat : null,
    lon: scene.isSuivre ? scene.live?.lon : null,
  });
  useRouteLayer(mapRef, {
    segments: scene.segments,
    customRoute: scene.customRoute,
    drawingMode: scene.drawingMode,
    drawnSegments: scene.drawnSegments,
    mapReady,
    visible: Boolean(scene.sceneReady) && !scene.drawingMode,
    paintMain: false,
    clockVertices: scene.clockVertices,
    traveledNm: scene.traveledNm,
  });

  useEffect(() => {
    onLayerState?.(maritimeLayers);
  }, [maritimeLayers, onLayerState]);

  useEffect(() => {
    onClimatologyState?.(climoLayer);
  }, [climoLayer, onClimatologyState]);

  useEffect(() => {
    const controller = controllerRef.current;
    if (!controller || !mapReady) return;
    controller.setCallbacks({
      onPlayback: (snapshot) => callbacksRef.current.onPlayback?.(snapshot),
      onCameraPlaced: (placed) => callbacksRef.current.onCameraPlaced?.(placed),
      onManualNavigation: () => callbacksRef.current.onManualNavigation?.(),
      onBoatDrag: (position) => callbacksRef.current.onBoatDrag?.(position),
      onWaypointHover: (point) => callbacksRef.current.onWaypointHover?.(point),
      onDrawingWaypointClick: (point, index) => callbacksRef.current.onDrawingWaypointClick?.(point, index),
      onWaypointClick: (point, index) => callbacksRef.current.onWaypointClick?.(point, index),
    });
    controller.update(scene);
  }, [mapReady, scene]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return undefined;
    map._biSuspendCatalogPick = Boolean(scene.drawingMode);
    const onClick = (event) => {
      const { lat, lng: lon } = event.latlng;
      if (scene.drawingMode) {
        callbacksRef.current.onDrawingClick?.(lat, lon);
        return;
      }
      const active = scene.customRoute ? featuresToSegments(scene.customRoute) : scene.segments;
      if (isNearRoute(map, lat, lon, active)) callbacksRef.current.onRouteClick?.({ lat, lon });
    };
    const onContextMenu = (event) => {
      L.DomEvent.preventDefault(event);
      callbacksRef.current.onCoordinatesCopied?.(
        `${event.latlng.lat.toFixed(6)}, ${wrapLon(event.latlng.lng).toFixed(6)}`,
      );
    };
    map.on("click", onClick);
    map.on("contextmenu", onContextMenu);
    map.getContainer().style.cursor = scene.drawingMode ? "crosshair" : "";
    return () => {
      map.off("click", onClick);
      map.off("contextmenu", onContextMenu);
      map.getContainer().style.cursor = "";
    };
  }, [mapReady, scene]);

  return <div ref={containerRef} id="simulator-map" style={{ height: "100%", width: "100%" }} />;
}

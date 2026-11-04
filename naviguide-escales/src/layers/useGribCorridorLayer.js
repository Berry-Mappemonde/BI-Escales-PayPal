import { useEffect, useRef } from "react";
import L from "leaflet";
import { corridorForBoat } from "../utils/gribCorridor.js";
import {
  gribBarbSvg,
  gribDisplayPoints,
  waveHsColor,
} from "../utils/gribSymbols.js";
import { cameraLngForBoat, markerWorldLngs, wrapLon } from "../utils/waypointFlags.js";
import { decimateByZoom, LAYER_DRAW_CAPS } from "../engine/layerWarm.js";

function lonNearBox(lon, west, east) {
  const x = Number(lon);
  const w = Number(west);
  const e = Number(east);
  if (w <= e) return x >= w - 2 && x <= e + 2;
  return x >= w - 2 || x <= e + 2;
}

function sampleNearBox(s, south, north, west, east) {
  if (s.lat == null || s.lon == null) return false;
  if (s.lat < south - 1 || s.lat > north + 1) return false;
  const copies = markerWorldLngs(s.lon);
  return copies.some((lng) => lonNearBox(lng, west, east) || lonNearBox(lng, wrapLon(west), wrapLon(east)));
}

function cellKey(value) {
  return value == null ? null : Math.round(Number(value) * 20) / 20;
}

function sampleKey(sample, index) {
  if (sample.stencil) return `stencil:${sample.stencilIndex ?? index}`;
  return `${Number(sample.lat).toFixed(3)},${Number(sample.lon).toFixed(3)}`;
}

function removeMissing(group, layers, expected) {
  layers.forEach((layer, key) => {
    if (expected.has(key)) return;
    group.removeLayer(layer);
    layers.delete(key);
  });
}

/** Barbules OMM + disques Hs en stencil. Jamais un rectangle de couloir. */
export function useGribCorridorLayer(mapRef, { grib, mapReady, visible, whenIso, lat, lon }) {
  const groupRef = useRef(null);
  const waveRef = useRef(new Map());
  const barbRef = useRef(new Map());
  const latCell = cellKey(lat);
  const lonCell = cellKey(lon);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return undefined;
    if (!groupRef.current) groupRef.current = L.layerGroup().addTo(map);
    const group = groupRef.current;
    if (!visible || grib?.status !== "ready") {
      removeMissing(group, waveRef.current, new Set());
      removeMissing(group, barbRef.current, new Set());
      return undefined;
    }
    const camLon = cameraLngForBoat(lonCell, map.getCenter()?.lng);
    const box = corridorForBoat(grib.bbox, latCell, camLon);
    if (!box) return undefined;
    const [south, north, west, east] = box;

    const near = (grib.samples || []).filter((s) => sampleNearBox(s, south, north, west, east));
    const slice = decimateByZoom(gribDisplayPoints(near.length ? near : grib.samples, {
      lat: latCell,
      lon: camLon,
      whenIso,
    }), map.getZoom(), LAYER_DRAW_CAPS.grib);
    const pane = map.getPane("grib") ? "grib" : "overlayPane";
    const cam = Number.isFinite(camLon) ? camLon : map.getCenter()?.lng;
    const nextWaves = new Set();
    const nextBarbs = new Set();
    for (const [sampleIndex, s] of slice.entries()) {
      for (const [copyIndex, lng] of markerWorldLngs(s.lon, cam).entries()) {
        const key = `${sampleKey(s, sampleIndex)}:${copyIndex}`;
        if (s.hs != null) {
          nextWaves.add(key);
          const color = waveHsColor(s.hs);
          const wave = waveRef.current.get(key);
          if (wave) {
            wave.setLatLng([s.lat, lng]);
            wave.setStyle({ color, fillColor: color });
          } else {
            waveRef.current.set(key, L.circleMarker([s.lat, lng], {
              radius: 10,
              color,
              fillColor: color,
              fillOpacity: 0.38,
              weight: 0,
              pane,
              interactive: false,
            }).addTo(group));
          }
        }
        if (s.windKnots == null) continue;
        nextBarbs.add(key);
        const html = gribBarbSvg(s);
        const barb = barbRef.current.get(key);
        if (barb) {
          barb.setLatLng([s.lat, lng]);
          if (barb._naviguideHtml !== html) {
            barb._naviguideHtml = html;
            const node = barb.getElement();
            if (node) node.innerHTML = html;
          }
        } else {
          const marker = L.marker([s.lat, lng], {
            icon: L.divIcon({
              className: "grib-barb",
              html,
              iconSize: [36, 36],
              iconAnchor: [18, 18],
            }),
            pane,
            interactive: false,
            keyboard: false,
          }).addTo(group);
          marker._naviguideHtml = html;
          barbRef.current.set(key, marker);
        }
      }
    }
    removeMissing(group, waveRef.current, nextWaves);
    removeMissing(group, barbRef.current, nextBarbs);
  }, [mapRef, mapReady, visible, grib, whenIso, latCell, lonCell]);

  useEffect(() => () => {
    groupRef.current?.remove();
    groupRef.current = null;
    waveRef.current.clear();
    barbRef.current.clear();
  }, []);
}

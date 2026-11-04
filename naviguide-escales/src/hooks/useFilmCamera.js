import { useEffect, useRef } from "react";
import { haversineNm } from "../utils/geo.js";
import { cameraLngForBoat } from "../utils/waypointFlags.js";
import { isAirPhase } from "../engine/filmCast.js";

const TELEPORT_NM = 80;

function zoomForRemaining(nm) {
  if (nm > 1800) return 3;
  if (nm > 500) return 4;
  if (nm > 120) return 5;
  if (nm > 30) return 6;
  return 7;
}

function unwrapPair(prev, lon) {
  return cameraLngForBoat(lon, prev);
}

function revealQuietTiles(map) {
  if (!map || typeof map.eachLayer !== "function") return;
  map.eachLayer((layer) => {
    const url = layer?._url || layer?._naviguideUrl;
    if (!url) return;
    const tiles = layer._tiles;
    if (tiles && typeof tiles === "object") {
      for (const tile of Object.values(tiles)) {
        const el = tile?.el || tile;
        if (!el?.style || el.style.visibility !== "hidden") continue;
        if (el.complete && el.naturalWidth > 0) el.style.visibility = "";
      }
    }
    if (typeof layer.redraw === "function") {
      try { layer.redraw(); } catch { /* couche déjà retirée */ }
    }
  });
}

function invalidateFilmMap(map) {
  if (!map || typeof map.invalidateSize !== "function") return;
  try {
    map.invalidateSize({ animate: false, pan: false });
  } catch {
    try { map.invalidateSize(); } catch { /* carte détruite */ }
  }
  revealQuietTiles(map);
}

/** Après Stop : recalcule la taille et réaffiche les tuiles complètes cachées. */
export function releaseFilmMap(sceneOrMap) {
  const map = sceneOrMap?.map && typeof sceneOrMap.map.invalidateSize === "function"
    ? sceneOrMap.map
    : sceneOrMap;
  if (!map || typeof map.invalidateSize !== "function") return false;
  invalidateFilmMap(map);
  const raf = typeof requestAnimationFrame === "function" ? requestAnimationFrame : null;
  if (raf) raf(() => raf(() => invalidateFilmMap(map)));
  return true;
}

/** Vue Suivre : on ne recentre pas sur le bateau du film. */
export function restoreFollowView(sceneOrMap, live) {
  releaseFilmMap(sceneOrMap);
  const lat = Number(live?.lat);
  const lon = Number(live?.lon);
  return {
    view: "suivre",
    follow: true,
    movedToFilm: false,
    lat: Number.isFinite(lat) ? lat : null,
    lon: Number.isFinite(lon) ? lon : null,
  };
}

/** Suit le bateau seulement si follow (cinéma). Le zoom utilisateur n’est pas volé. */
export function useFilmCamera({
  mapRef,
  mapReady,
  enabled,
  lat,
  lon,
  remainingNm,
  playing,
  jumpToken,
  phase,
  hopFrom,
  hopTo,
  resetKey = "",
  follow = false,
  recaptureToken = 0,
  focusToken = 0,
  onProgrammaticMove,
}) {
  const lastFollow = useRef(0);
  const lastJump = useRef(0);
  const lastPos = useRef(null);
  const followLon = useRef(null);
  const lastPhase = useRef(null);
  const lastReset = useRef(resetKey);
  const lastRecapture = useRef(recaptureToken);
  const lastFocus = useRef(focusToken);

  if (lastReset.current !== resetKey) {
    lastReset.current = resetKey;
    lastFollow.current = 0;
    lastJump.current = 0;
    lastPos.current = null;
    followLon.current = null;
    lastPhase.current = null;
    lastFocus.current = focusToken;
  }

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady || !enabled || lat == null || lon == null) return;

    const lonCam = unwrapPair(followLon.current, lon);
    followLon.current = lonCam;
    const prev = lastPos.current;
    const movedNm = prev ? haversineNm(prev.lat, prev.lon, lat, lon) : 0;
    lastPos.current = { lat, lon };
    const z = zoomForRemaining(remainingNm);
    const tokenJump = jumpToken && jumpToken !== lastJump.current;
    if (tokenJump) lastJump.current = jumpToken;
    const phaseChanged = phase && phase !== lastPhase.current;
    if (phase) lastPhase.current = phase;
    const recapture = recaptureToken !== lastRecapture.current;
    if (recapture) lastRecapture.current = recaptureToken;
    const focus = focusToken !== lastFocus.current;
    if (focus) lastFocus.current = focusToken;

    const move = (fn) => {
      onProgrammaticMove?.();
      fn();
    };

    if (isAirPhase(phase) && hopFrom && hopTo) {
      if (follow && (phaseChanged || tokenJump || recapture)) {
        const lonA = unwrapPair(followLon.current, hopFrom.lon);
        const lonB = unwrapPair(lonA, hopTo.lon);
        followLon.current = lonB;
        move(() => map.fitBounds(
          [
            [hopFrom.lat, lonA],
            [hopTo.lat, lonB],
          ],
          { padding: [72, 96], maxZoom: 3.15, animate: true, duration: 0.9 },
        ));
        lastFollow.current = Date.now();
        lastPos.current = null;
      }
      return;
    }

    if (focus) {
      move(() => map.setView([lat, lonCam], map.getZoom(), { animate: false }));
      lastFollow.current = Date.now();
      return;
    }

    if (recapture || prev == null) {
      move(() => map.setView([lat, lonCam], z, { animate: false }));
      lastFollow.current = Date.now();
      return;
    }

    if (!follow) return;

    const teleport = tokenJump || phaseChanged || movedNm >= TELEPORT_NM;
    if (teleport) {
      move(() => map.flyTo([lat, lonCam], z, { duration: movedNm >= TELEPORT_NM || phaseChanged ? 0.7 : 1.05 }));
      lastFollow.current = Date.now();
      return;
    }

    if (!playing) return;
    const now = Date.now();
    if (now - lastFollow.current < 700) return;
    lastFollow.current = now;
    const cur = map.getZoom();
    const zoom = Math.abs(cur - z) >= 1.25 ? z : cur;
    move(() => map.setView([lat, lonCam], zoom, { animate: true, duration: 0.55 }));
  }, [mapRef, mapReady, enabled, lat, lon, remainingNm, playing, jumpToken, phase, hopFrom?.lat, hopFrom?.lon, hopTo?.lat, hopTo?.lon, resetKey, follow, recaptureToken, focusToken, onProgrammaticMove]);
}

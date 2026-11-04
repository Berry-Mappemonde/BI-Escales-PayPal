import { useCallback, useEffect, useRef, useState } from "react";
import { useEscaleSheet } from "./useEscaleSheet.js";
import {
  escaleSheetVisible, nearestAlongside, parkedCatamaranSample, pickAutoEscaleStop,
} from "./escaleSheetPick.js";

export { escaleSheetVisible, nearestAlongside, parkedCatamaranSample, pickAutoEscaleStop };

/**
 * Which stop's sheet is open (moved out of App.jsx): opened
 * from a flag click, and by itself when the boat is alongside (Suivre =
 * live officiel ; Tracer = playhead du tracé) — once per stop,
 * the skipper may close it.
 * `clearToken` : Suivre / Revoir vident la fiche et bloquent le
 * ré-auto-open immédiat. `filmActive` : pas de fiche pendant le film.
 * `userPickedRef` : une fiche désignée n'est pas écrasée par l'auto-quai.
 */
export function useEscaleSheetState({
  lang, isSuivre, atQuay, clockSample, marks, onOpen, filmActive = false, clearToken = 0,
  clockMoveToken = 0,
}) {
  const [stop, setStop] = useState(null);
  const sheet = useEscaleSheet(stop, lang);
  const autoRef = useRef(null);
  const holdRef = useRef(false);
  const userPickedRef = useRef(false);

  const open = useCallback((next) => {
    if (!next || !Number.isFinite(next.lat) || !Number.isFinite(next.lon)) return;
    holdRef.current = false;
    userPickedRef.current = true;
    autoRef.current = next.name;
    setStop({ name: next.name, lat: next.lat, lon: next.lon });
    onOpen?.();
  }, [onOpen]);

  const close = useCallback(() => {
    userPickedRef.current = false;
    holdRef.current = true; // fermer ne rouvre pas aussitôt la fiche du quai
    if (stop) autoRef.current = stop.name;
    setStop(null);
  }, [stop]);

  useEffect(() => {
    if (!clearToken) return;
    holdRef.current = true;
    userPickedRef.current = false;
    if (stop) autoRef.current = stop.name;
    const near = nearestAlongside(clockSample, marks);
    if (near) autoRef.current = near.name;
    setStop(null);
    // clockSample / marks / stop : on fige l'escale courante au moment du nav.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clearToken]);

  useEffect(() => {
    if (!atQuay) holdRef.current = false;
  }, [atQuay]);

  // The sheet belongs to the stop the boat is at: once the clock carries
  // the boat away from it, the sheet closes and the stop may auto-open again.
  // A flag click holds its sheet until the skipper moves the clock.
  const [released, setReleased] = useState(0);
  useEffect(() => {
    if (!clockMoveToken || !userPickedRef.current) return;
    userPickedRef.current = false;
    setReleased((n) => n + 1);
  }, [clockMoveToken]);
  const visible = escaleSheetVisible({ stop, clockSample, userPicked: userPickedRef.current });
  useEffect(() => {
    if (!stop || visible) return;
    userPickedRef.current = false;
    if (autoRef.current === stop.name) autoRef.current = null;
    setStop(null);
  }, [stop, visible, released]);

  useEffect(() => {
    if (filmActive) {
      holdRef.current = true;
      userPickedRef.current = false;
      if (stop) setStop(null);
      return;
    }
    const best = pickAutoEscaleStop({
      filmActive,
      hold: holdRef.current,
      userPicked: userPickedRef.current,
      isSuivre,
      atQuay,
      clockSample,
      marks,
    });
    if (!best || autoRef.current === best.name) return;
    autoRef.current = best.name;
    setStop({ name: best.name, lat: best.lat, lon: best.lon });
  }, [filmActive, isSuivre, atQuay, clockSample, marks, stop]);

  return { stop: visible ? stop : null, setStop, sheet, open, close };
}

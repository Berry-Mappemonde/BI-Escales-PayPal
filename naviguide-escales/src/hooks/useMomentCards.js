import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { advanceMoments, cardsFromOfficialMoments, dismissNow, emptyMoments, nextFree, selectDisplayedMoments } from "../engine/momentCard.js";
import { validMomentPosition } from "./useMoment.js";

const TICK_MS = 1000;

/**
 * La carte du moment : une carte NOW (sécurité / décision) et un bloc FREE
 * (information) nourris par le registre d’événements jugés et le sac
 * `ici()`. Un tick par seconde fait vivre les expirations ; tout le reste
 * est pur (`engine/momentCard.js`). Ne bloque jamais la lecture.
 */
export function useMomentCards({
  enabled = true,
  events,
  bag,
  filmCum,
  playing = false,
  mode = "simulation",
  lang = "fr",
  written = false,
  legId = null,
  leg = null,
  officialMoments = null,
  nowIso = null,
  boat = null,
  legProgress = null,
}) {
  // Rounded so a moving boat does not rebuild the cards on every frame.
  const boatPos = validMomentPosition(boat?.lat, boat?.lon);
  const boatLat = boatPos ? Math.round(boatPos.lat * 100) / 100 : null;
  const boatLon = boatPos ? Math.round(boatPos.lon * 100) / 100 : null;
  const boatAt = useMemo(
    () => (boatLat == null || boatLon == null ? null : { lat: boatLat, lon: boatLon }),
    [boatLat, boatLon],
  );
  const [state, setState] = useState(() => emptyMoments());
  const inputRef = useRef({ events, bag, filmCum, playing, mode, lang, written, legId, leg });
  inputRef.current = { events, bag, filmCum, playing, mode, lang, written, legId, leg };

  const step = useCallback((nowMs = Date.now()) => {
    setState((prev) => advanceMoments(prev, { ...inputRef.current, nowMs }));
  }, []);

  // New inputs → one step right away (a fresh event shows without waiting the tick).
  useEffect(() => {
    if (!enabled) return;
    step();
  }, [enabled, events, bag, filmCum, playing, mode, lang, written, legId, leg, step]);

  useEffect(() => {
    if (!enabled) return undefined;
    const id = setInterval(() => step(), TICK_MS);
    return () => clearInterval(id);
  }, [enabled, step]);

  useEffect(() => {
    if (!enabled) setState(emptyMoments());
  }, [enabled]);

  const official = useMemo(
    () => cardsFromOfficialMoments(officialMoments, { until: nowIso, boat: boatAt, lang }),
    [officialMoments, nowIso, boatAt, lang],
  );
  const [officialUi, setOfficialUi] = useState({ hideNow: false, freeIndex: 0 });
  const officialKey = `${official.now?.key || ""}|${official.freeQueue.map((card) => card.key).join("|")}`;
  useEffect(() => {
    setOfficialUi({ hideNow: false, freeIndex: 0 });
  }, [officialKey]);

  const dismiss = useCallback(() => {
    setState((prev) => dismissNow(prev, Date.now()));
    setOfficialUi((prev) => ({ ...prev, hideNow: true }));
  }, []);
  const next = useCallback(() => {
    setState((prev) => nextFree(prev, Date.now()));
    setOfficialUi((prev) => ({ ...prev, freeIndex: prev.freeIndex + 1 }));
  }, []);

  // Recette (dev only): `window.__naviguideMoments` shows queues and inputs.
  if (import.meta.env?.DEV && typeof window !== "undefined") {
    window.__naviguideMoments = { state, enabled, inputs: inputRef.current };
  }

  const eventNow = enabled ? state.now : null;
  const eventFree = enabled && !eventNow ? state.free : null;
  const officialNow = enabled && !officialUi.hideNow ? official.now : null;
  // « Suivant » boucle sur la file : cliquer après la dernière carte ne l'efface plus.
  const freeCount = official.freeQueue.length;
  const officialFree = enabled && freeCount ? official.freeQueue[officialUi.freeIndex % freeCount] : null;
  const shown = selectDisplayedMoments({
    eventNow,
    eventFree,
    officialNow,
    officialHasNow: Boolean(enabled && official.now),
    officialFree,
    boat: boatAt,
    leg: legProgress,
  });
  return {
    now: shown.now,
    free: shown.free,
    freeLeft: state.freeQueue.length || Math.max(0, official.freeQueue.length - officialUi.freeIndex - 1),
    nowLeft: state.nowQueue.length,
    dismiss,
    next,
  };
}

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  BOAT_FIELDS,
  COMFORTS,
  DEFAULT_PROFILE,
  EXPERT_IDS,
  HORIZONS_H,
  PROFILES,
  clampBoat,
  clampExpert,
  clearSavedOrders,
  ordersLine,
  readSavedOrders,
  resolveOrders,
  sanitizeSaved,
  writeSavedOrders,
} from "../engine/skipperOrders.js";

const NOTICE_MS = 6000;

function storage() {
  try {
    return typeof window !== "undefined" ? window.localStorage : null;
  } catch {
    return null;
  }
}

function suggestKey(orders) {
  if (!orders?.suggest) return null;
  return `${orders.boat?.expeditionId || orders.boat?.name || "polar"}:${orders.suggest.profile}`;
}

/** What the cyan line reacts to: character, comfort, horizon. Not Expert keystrokes. */
function noticeKey(saved) {
  return `${saved.profile}|${saved.comfort || "normal"}|${saved.horizonH || ""}`;
}

/**
 * Skipper orders: one character, saved in this tab (localStorage, same key since v1:
 * profile + S6 comfort / horizonH + S7 expert).
 * Never awaits a model. Never rewinds the film. Cinema keeps the orders active.
 * A small polar proposes Coastal; it never switches silently.
 */
/**
 * Wind of the moment, rounded so the orders only change when the polar would
 * read another cell: 1 kn, 10° of angle. Null when unknown.
 */
export function roundedWind(wind) {
  const tws = Number(wind?.tws);
  const twd = Number(wind?.twd);
  const heading = Number(wind?.heading);
  if (![tws, twd, heading].every(Number.isFinite)) return null;
  return {
    tws: Math.round(tws),
    twd: Math.round(twd / 10) * 10,
    heading: Math.round(heading / 10) * 10,
    kind: wind?.kind === "climatology" ? "climatology" : "grib",
  };
}

export function useSkipperOrders({ polar = null, mode = "simulation", lang = "fr", wind = null } = {}) {
  const [saved, setSaved] = useState(
    () => readSavedOrders(storage()) ?? { profile: DEFAULT_PROFILE },
  );
  const [notice, setNotice] = useState(null);
  const [dismissed, setDismissed] = useState(null);
  const timerRef = useRef(null);
  const shownRef = useRef(noticeKey(saved));

  const w = roundedWind(wind);
  const windKey = w ? `${w.tws}|${w.twd}|${w.heading}|${w.kind}` : "";
  const orders = useMemo(
    () => resolveOrders(saved, { polar, mode, wind: w }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [saved, polar, mode, windKey],
  );
  const profile = orders.profile;

  useEffect(() => {
    // One cyan line per orders change only — not at boot (StrictMode runs
    // effects twice), not on polar / mode / lang changes, not per Expert keystroke.
    const key = noticeKey(saved);
    if (shownRef.current === key) return undefined;
    shownRef.current = key;
    setNotice(ordersLine(orders, lang));
    clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => setNotice(null), NOTICE_MS);
    return () => clearTimeout(timerRef.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [saved]);

  const update = useCallback((patch) => {
    setSaved((prev) => {
      const next = sanitizeSaved({ ...prev, ...patch });
      if (JSON.stringify(next) === JSON.stringify(prev)) return prev;
      writeSavedOrders(storage(), next);
      return next;
    });
  }, []);

  const setProfile = useCallback((next) => {
    if (!PROFILES.includes(next)) return;
    update({ profile: next });
  }, [update]);

  const setComfort = useCallback((next) => {
    if (!COMFORTS.includes(next)) return;
    update({ comfort: next });
  }, [update]);

  const setHorizon = useCallback((hours) => {
    const h = Number(hours);
    update({ horizonH: HORIZONS_H.includes(h) ? h : undefined });
  }, [update]);

  /** setExpert(id, value) forces one number; setExpert(id, null) hands it back to the profile. */
  const setExpert = useCallback((id, value) => {
    if (!EXPERT_IDS.includes(id)) return;
    setSaved((prev) => {
      const expert = { ...(prev.expert || {}) };
      const v = value == null || value === "" ? null : clampExpert(id, value);
      if (v == null) delete expert[id];
      else expert[id] = v;
      const next = sanitizeSaved({ ...prev, expert });
      if (JSON.stringify(next) === JSON.stringify(prev)) return prev;
      writeSavedOrders(storage(), next);
      return next;
    });
  }, []);

  /** setBoat("loaM", 12) types the boat's length / draft; setBoat(id, null) goes back to the polar. */
  const setBoat = useCallback((id, value) => {
    if (!(id in BOAT_FIELDS)) return;
    setSaved((prev) => {
      const boat = { ...(prev.boat || {}) };
      const v = value == null || value === "" ? null : clampBoat(id, value);
      if (v == null) delete boat[id];
      else boat[id] = v;
      const next = sanitizeSaved({ ...prev, boat });
      if (JSON.stringify(next) === JSON.stringify(prev)) return prev;
      writeSavedOrders(storage(), next);
      return next;
    });
  }, []);

  const reset = useCallback(() => {
    clearSavedOrders(storage());
    setSaved({ profile: DEFAULT_PROFILE });
  }, []);

  const key = suggestKey(orders);
  const suggest = orders.suggest && dismissed !== key ? orders.suggest : null;
  const acceptSuggest = useCallback(() => {
    if (orders.suggest) setProfile(orders.suggest.profile);
  }, [orders.suggest, setProfile]);
  const dismissSuggest = useCallback(() => setDismissed(key), [key]);

  return {
    orders,
    profile,
    comfort: orders.comfort,
    horizonH: orders.knobs.horizonH,
    expert: orders.expert,
    setProfile,
    setComfort,
    setHorizon,
    setExpert,
    setBoat,
    reset,
    notice,
    suggest,
    acceptSuggest,
    dismissSuggest,
  };
}

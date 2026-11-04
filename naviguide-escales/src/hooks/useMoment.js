import { useEffect, useState } from "react";
import { wrapLon } from "../utils/geo.js";
import fixture from "../fixtures/moment.json" with { type: "json" };

const API_URL = import.meta.env?.VITE_API_URL ?? "";

export const MOMENT_FIXTURE = fixture;

export function isMoment(body) {
  return Boolean(body && typeof body === "object" && typeof body.signature === "string" && body.signature);
}

/** A coordinate as a number, or null. `null`, `undefined` and "" are not 0. */
export function finiteCoord(value) {
  if (value == null || value === "" || typeof value === "boolean") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

/** { lat, lon } when both are real coordinates, else null (no request). */
export function validMomentPosition(lat, lon) {
  const la = finiteCoord(lat);
  const lo = finiteCoord(lon);
  if (la == null || lo == null || Math.abs(la) > 90) return null;
  return { lat: la, lon: wrapLon(lo) };
}

/** Query string for GET /ici/moment, or null without a valid position.
 * Longitudes folded into [−180, 180]. */
export function momentSearchParams({ lat, lon, t, mode, lang } = {}) {
  const at = validMomentPosition(lat, lon);
  if (!at) return null;
  const q = new URLSearchParams({
    lat: String(at.lat),
    lon: String(at.lon),
  });
  if (t) q.set("t", String(t));
  if (mode) q.set("mode", String(mode));
  if (lang) q.set("lang", String(lang));
  return q;
}

function emptyMomentState(error = null) {
  return { moment: null, loading: false, error, source: "none" };
}

/**
 * Fetch a Moment from GET /ici/moment. Without lat/lon, or if the API
 * does not answer: moment is null (empty frame). MOMENT_FIXTURE stays
 * importable for tests and the R8b preview page — it is never the current
 * point.
 */
export function useMoment({
  lat,
  lon,
  t,
  mode = "follow",
  lang = "fr",
  enabled = true,
  frozen = false,
} = {}) {
  const [state, setState] = useState(emptyMomentState());

  useEffect(() => {
    if (frozen) return undefined;
    // Number(null) is 0: a missing position must not become lat=null&lon=0.
    const q = enabled ? momentSearchParams({ lat, lon, t, mode, lang }) : null;
    if (!q) {
      setState(emptyMomentState());
      return undefined;
    }
    const controller = new AbortController();
    setState((prev) => ({ ...prev, loading: true }));
    fetch(`${API_URL}/ici/moment?${q}`, { signal: controller.signal })
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((body) => {
        if (!isMoment(body)) throw new Error("moment invalide");
        setState({ moment: body, loading: false, error: null, source: "api" });
      })
      .catch((err) => {
        if (err?.name === "AbortError") return;
        setState(emptyMomentState(err?.message || "error"));
      });
    return () => controller.abort();
  }, [enabled, frozen, lat, lon, t, mode, lang]);

  return state;
}

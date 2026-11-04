import { useEffect, useMemo, useState } from "react";
import { trueWindAngle } from "../engine/playSpeeds.js";
import { polarBoatSpeed } from "../engine/polarSpeed.js";
import { clockWindSeries } from "../engine/voyageClock.js";
import {
  cacheKeyLatLon,
  mapPool,
  pickProfileSamples,
} from "../engine/routeWindProfile.js";
import { pollWeatherUntil } from "./weatherSnapshot.js";

const API_URL = import.meta.env.VITE_API_URL ?? "";
const POLAR_API_URL = import.meta.env.VITE_POLAR_API_URL ?? import.meta.env.VITE_API_URL ?? "";

const windCache = new Map();
const polarCache = new Map();

async function fetchWind(lat, lon) {
  const key = cacheKeyLatLon(lat, lon);
  if (windCache.has(key)) return windCache.get(key);
  const body = await pollWeatherUntil(
    async () => {
      const res = await fetch(`${API_URL}/wind`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ latitude: lat, longitude: lon }),
      });
      if (!res.ok) throw new Error("wind");
      return res.json();
    },
    (row) => row?.status === "ready" && Number.isFinite(Number(row.wind_speed_knots)),
  );
  const wind = {
    tws: Number(body?.wind_speed_knots),
    from: Number(body?.wind_direction),
  };
  if (!Number.isFinite(wind.tws)) throw new Error("wind");
  windCache.set(key, wind);
  return wind;
}

async function fetchPolarKnots(expeditionId, twa, tws) {
  if (!expeditionId) return null;
  const key = `${expeditionId}:${Math.round(twa)}:${Math.round(tws)}`;
  if (polarCache.has(key)) return polarCache.get(key);
  const res = await fetch(
    `${POLAR_API_URL}/api/v1/polar/${encodeURIComponent(expeditionId)}/speed?twa=${twa}&tws=${tws}`,
  );
  if (!res.ok) return null;
  const body = await res.json();
  const k = Number(body.speed);
  if (!Number.isFinite(k) || k <= 0) return null;
  polarCache.set(key, k);
  return k;
}

/**
 * Mini wind / knots series along the track. Do not refetch on every tick.
 */
export function useRouteWindProfile({ flat, marks, polarData, cruiseKnots, enabled, clock = null }) {
  const clockSeries = useMemo(
    () => (enabled && clock ? clockWindSeries(clock) : []),
    [enabled, clock],
  );
  const samples = useMemo(
    () => (enabled && !clock ? pickProfileSamples(flat, marks, { maxPoints: 24 }) : []),
    [enabled, clock, flat, marks],
  );
  const sampleKey = useMemo(
    () => samples.map((s) => `${s.filmNm.toFixed(1)}:${s.lat.toFixed(2)}:${s.lon.toFixed(2)}`).join("|"),
    [samples],
  );
  const [series, setSeries] = useState([]);
  const [loading, setLoading] = useState(false);

  const cruise = Number(cruiseKnots) > 0 ? Number(cruiseKnots) : 7;
  const expeditionId = polarData?.expedition_id || "";
  const polarRaw = polarData?.raw;

  useEffect(() => {
    if (clockSeries.length) {
      setSeries(clockSeries);
      setLoading(false);
      return undefined;
    }
    if (!enabled || !samples.length) {
      setSeries([]);
      setLoading(false);
      return undefined;
    }
    let cancelled = false;
    setLoading(true);
    (async () => {
      const rows = await mapPool(samples, 3, async (s) => {
        let tws = null;
        let windFrom = null;
        let boat = cruise;
        try {
          const wind = await fetchWind(s.lat, s.lon);
          tws = wind.tws;
          windFrom = wind.from;
          const twa = trueWindAngle(s.heading, wind.from);
          const local = twa != null ? polarBoatSpeed(polarRaw, twa, wind.tws) : null;
          if (local != null && local > 0) boat = local;
          else if (twa != null && expeditionId) {
            const k = await fetchPolarKnots(expeditionId, twa, wind.tws);
            if (k != null) boat = k;
          }
        } catch {
          /* cruise only */
        }
        return { ...s, tws, windFrom, boatKnots: boat };
      });
      if (!cancelled) {
        setSeries(rows);
        setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [enabled, sampleKey, samples, expeditionId, cruise, polarRaw, clockSeries]);

  return { samples, series: clockSeries.length ? clockSeries : series, loading: clockSeries.length ? false : loading };
}

import { useEffect, useRef, useState } from "react";
import { expeditionBoatKnots, trueWindAngle } from "../engine/playSpeeds.js";
import { lerpSeries } from "../engine/routeWindProfile.js";
import { polarBoatSpeed } from "../engine/polarSpeed.js";
import { pollWeatherUntil } from "./weatherSnapshot.js";
import { resolveFollowSpeed } from "./expeditionSpeed.js";

export { resolveFollowSpeed };

const API_URL = import.meta.env.VITE_API_URL ?? "";
const POLAR_API_URL = import.meta.env.VITE_POLAR_API_URL ?? import.meta.env.VITE_API_URL ?? "";

function roundKt(k) {
  const n = Number(k);
  if (!Number.isFinite(n) || n <= 0) return null;
  return Math.round(n * 10) / 10;
}

/**
 * Film knots: clock table in Follow; planned polar × wind in Simulation.
 */
export function useExpeditionSpeed({
  polarData,
  sample,
  profile,
  playing,
  onLiveKnots,
  windSeries,
  filmNm,
  clockSample = null,
  follow = false,
}) {
  const cruise = expeditionBoatKnots(polarData);
  const [nrtKnots, setNrtKnots] = useState(null);
  const [climoKnots, setClimoKnots] = useState(null);
  const sampleRef = useRef(sample);
  const onLiveRef = useRef(onLiveKnots);
  const lastEmit = useRef(null);
  sampleRef.current = sample;
  onLiveRef.current = onLiveKnots;

  useEffect(() => {
    if (follow) return;
    const s = sample;
    const tws = lerpSeries(windSeries, filmNm, "tws");
    const from = lerpSeries(windSeries, filmNm, "windFrom");
    const twa = trueWindAngle(s?.bearing, from);
    let k = null;
    if (tws != null && twa != null) {
      k = polarBoatSpeed(polarData?.raw, twa, tws);
    }
    const rounded = roundKt(k);
    setClimoKnots(rounded);
    if (nrtKnots == null) {
      if (rounded !== lastEmit.current) {
        lastEmit.current = rounded;
        onLiveRef.current?.(rounded);
      }
    }
  }, [filmNm, sample?.bearing, windSeries, polarData?.raw, nrtKnots, follow]);

  useEffect(() => {
    if (follow) return undefined;
    if (profile !== "real" || !playing || !polarData?.expedition_id) return undefined;
    let cancelled = false;
    const tick = async () => {
      const s = sampleRef.current;
      if (!s) return;
      try {
        const wind = await pollWeatherUntil(
          async () => {
            const res = await fetch(`${API_URL}/wind`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ latitude: s.lat, longitude: s.lon }),
            });
            if (!res.ok) throw new Error("wind");
            return res.json();
          },
          (row) => row?.status === "ready" && Number.isFinite(Number(row.wind_speed_knots)),
        );
        const tws = Number(wind?.wind_speed_knots);
        const twa = trueWindAngle(s.bearing, Number(wind?.wind_direction));
        if (!Number.isFinite(tws) || twa == null) return;
        let k = polarBoatSpeed(polarData?.raw, twa, tws);
        if (k == null && polarData.expedition_id) {
          const spd = await fetch(
            `${POLAR_API_URL}/api/v1/polar/${encodeURIComponent(polarData.expedition_id)}/speed?twa=${twa}&tws=${tws}`,
          );
          if (spd.ok) {
            const body = await spd.json();
            k = Number(body.speed);
          }
        }
        const rounded = roundKt(k);
        if (!cancelled && rounded != null) {
          setNrtKnots(rounded);
          lastEmit.current = rounded;
          onLiveRef.current?.(rounded);
        }
      } catch {
        /* climatology / cruise */
      }
    };
    tick();
    const id = setInterval(tick, 25000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [profile, playing, polarData?.expedition_id, polarData?.raw, follow]);

  useEffect(() => {
    if (profile !== "real") {
      setNrtKnots(null);
    }
  }, [profile]);

  if (follow) {
    return { ...resolveFollowSpeed(clockSample), cruise };
  }
  const analyse = profile === "real" && nrtKnots != null;
  const knots = (analyse ? nrtKnots : climoKnots) || cruise;
  const kind = analyse ? "analyse" : (climoKnots != null ? "climatology" : null);
  return { knots, cruise, live: analyse, kind };
}

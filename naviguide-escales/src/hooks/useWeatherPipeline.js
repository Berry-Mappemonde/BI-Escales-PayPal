import { useMemo } from "react";

const OFF = new Set(["0", "false", "no", "off"]);

export function weatherPipelineEnabled(env) {
  const source = env ?? (typeof import.meta !== "undefined" ? import.meta.env : undefined);
  const raw = source?.VITE_NAVIGUIDE_WEATHER_PIPELINE ?? source?.NAVIGUIDE_WEATHER_PIPELINE;
  if (raw == null || String(raw).trim() === "") return true;
  return !OFF.has(String(raw).trim().toLowerCase());
}

/** Per-layer state for GRIB wind. */
export function gribWindLayerState(grib, enabled) {
  if (!enabled) return null;
  const explicit = grib?.layers?.gribWind?.status;
  if (explicit === "pending" || explicit === "ready" || explicit === "unavailable") return explicit;
  if (!grib) return "pending";
  if (grib.status === "ready") return "ready";
  if (grib.status === "pending" || grib.refreshing) return "pending";
  return "unavailable";
}

/** Wave, current, or other product body. */
export function productLayerState(product, enabled) {
  if (!enabled) return null;
  if (!product) return "pending";
  const explicit = product.status;
  if (explicit === "pending" || explicit === "ready" || explicit === "unavailable") return explicit;
  if (explicit === "error" || explicit === "absent") return "unavailable";
  if (product.refreshing) return "pending";
  return "unavailable";
}

/** Atlas Blue Intelligence. A cut atlas is unavailable; the map does not wait. */
export function climatologyLayerState(climo, enabled) {
  if (!enabled) return null;
  if (!climo) return "pending";
  if (climo.error) return "unavailable";
  if (climo.loading || climo.counts == null) return "pending";
  return "ready";
}

/**
 * First render never waits on a provider: the state is derived, and blocksMap stays false.
 * The flag no longer selects another path.
 */
export function useWeatherPipeline({ grib, wave, current, forecastWind, climatology } = {}) {
  const gribWind = useMemo(() => gribWindLayerState(grib, true), [grib]);
  const waveState = useMemo(() => productLayerState(wave, true), [wave]);
  const currentState = useMemo(() => productLayerState(current, true), [current]);
  const forecastWindState = useMemo(() => productLayerState(forecastWind, true), [forecastWind]);
  const climatologyState = useMemo(() => climatologyLayerState(climatology, true), [climatology]);
  return {
    enabled: true,
    blocksMap: false,
    layers: {
      gribWind,
      wave: waveState,
      current: currentState,
      forecastWind: forecastWindState,
      climatology: climatologyState,
    },
  };
}

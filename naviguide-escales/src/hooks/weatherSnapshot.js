/** Pipeline météo partagé : statut immédiat, poll court, refresh lent. */

import { wrapLon } from "../utils/geo.js";

export const WEATHER_POLL_MS = 4000;
export const WEATHER_REFRESH_MS = 60_000;

export function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export function productHasData(product, kind) {
  if (!product) return false;
  if (kind === "wind") {
    return Number.isFinite(Number(product.wind_speed_knots ?? product.speedKnots));
  }
  if (kind === "wave") {
    return Number.isFinite(Number(product.significant_wave_height_m ?? product.hs));
  }
  if (kind === "current") {
    return Number.isFinite(Number(product.speed_knots ?? product.speedKnots));
  }
  return false;
}

export function weatherPending(body) {
  if (!body) return true;
  return body.status === "pending" || (Boolean(body.refreshing) && body.status !== "ready");
}

export function satelliteBusy(body) {
  if (!body) return true;
  const has = ["wind", "wave", "current"].some((kind) => (
    productHasData(body[kind], kind) || productHasData(body, kind)
  ));
  return weatherPending(body) && !has;
}

export function weatherPollMs(body) {
  return weatherPending(body) ? WEATHER_POLL_MS : WEATHER_REFRESH_MS;
}

export async function fetchWeatherComposite(lat, lon, { signal, api = "" } = {}) {
  const res = await fetch(`${api}/weather`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ latitude: lat, longitude: wrapLon(Number(lon)) }),
    signal,
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export async function fetchWeatherForecast(lat, lon, { signal, api = "" } = {}) {
  const q = new URLSearchParams({ lat: String(lat), lon: String(wrapLon(Number(lon))) });
  const res = await fetch(`${api}/weather/forecast?${q}`, { signal });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export async function pollWeatherUntil(fetchOnce, isDone, {
  signal,
  timeoutMs = 12_000,
  intervalMs = 400,
} = {}) {
  const start = Date.now();
  let delay = intervalMs;
  let last = null;
  while (Date.now() - start < timeoutMs) {
    if (signal?.aborted) {
      const err = new Error("aborted");
      err.name = "AbortError";
      throw err;
    }
    last = await fetchOnce();
    if (isDone(last)) return last;
    await sleep(delay);
    delay = Math.min(delay * 1.5, WEATHER_POLL_MS);
  }
  return last;
}

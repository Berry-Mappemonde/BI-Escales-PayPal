import { atlasLayerUrl, atlasTileUrl } from "../utils/atlasPoint.js";

/**
 * Atlas coupé : une tuile (ou la couche globale) en échec n'est pas redemandée
 * avant ce délai. Sans cette pause, chaque déplacement de vue relançait toutes
 * les tuiles et le repli global, et la rafale retardait le clic de point.
 * La pause vit à part du cache de session : rien d'« unavailable » n'y entre.
 */
export const UNAVAILABLE_RETRY_MS = 30_000;
const UNAVAILABLE_UNTIL = new Map();

export async function fetchJson(url, signal) {
  const r = await fetch(url, { signal });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  const body = await r.json();
  // Le proxy répond 200 « unavailable » quand l'atlas est coupé : c'est un échec,
  // pas une tuile vide à garder en cache pour toute la session.
  if (body?.status === "unavailable") {
    const err = new Error("atlas unavailable");
    err.atlasUnavailable = true;
    throw err;
  }
  return body;
}

/** True only when every tile failed with an HTTP error. Abort, a live tile, or an atlas
 *  that answers « unavailable » does not open the global geojson (26 Mo). */
export function allTilesErrored(outcomes) {
  if (!outcomes.length) return false;
  if (outcomes.some((o) => o === "abort" || o === "unavailable")) return false;
  return outcomes.every((o) => o === "error");
}

export async function loadClimoLayerFeatures({
  kind,
  month,
  extra = {},
  tiles,
  cache,
  cacheKey,
  fetchJson: fetchFn = fetchJson,
  signal,
  cooldown = UNAVAILABLE_UNTIL,
  now = Date.now,
}) {
  const collections = [];
  const resting = (key) => {
    const until = cooldown?.get(key);
    if (until == null) return false;
    if (until > now()) return true;
    cooldown.delete(key);
    return false;
  };
  const rest = (key, err) => {
    if (err?.atlasUnavailable) cooldown?.set(key, now() + UNAVAILABLE_RETRY_MS);
  };
  const outcomes = [];
  const keyOf = cacheKey || ((tile) => `${kind}:${month}:${tile.z}/${tile.x}/${tile.y}`);

  await Promise.all((tiles || []).map(async (tile) => {
    const key = keyOf(tile);
    const hit = cache?.get(key);
    if (hit?.features) {
      outcomes.push("ok");
      collections.push(hit.features);
      return;
    }
    if (resting(key)) {
      outcomes.push("unavailable");
      collections.push([]);
      return;
    }
    try {
      const data = await fetchFn(atlasTileUrl(kind, month, tile.z, tile.x, tile.y, extra), signal);
      const features = data?.features || [];
      cache?.set(key, { features });
      outcomes.push("ok");
      collections.push(features);
    } catch (err) {
      if (err?.name === "AbortError") {
        outcomes.push("abort");
        collections.push(null);
        return;
      }
      rest(key, err);
      if (err?.atlasUnavailable) {
        outcomes.push("unavailable");
        collections.push([]);
        return;
      }
      outcomes.push("error");
      collections.push([]);
    }
  }));

  if (signal?.aborted) {
    return { features: [], source: "tiles", aborted: true };
  }

  if (allTilesErrored(outcomes)) {
    const globalKey = `${kind}:${month}:global:${JSON.stringify(extra)}`;
    if (resting(globalKey)) return { features: [], source: null, aborted: false };
    try {
      const data = await fetchFn(
        atlasLayerUrl(kind, month, { ...extra, spacing_deg: "4" }),
        signal,
      );
      return { features: data?.features || [], source: "global", aborted: false };
    } catch (err) {
      if (err?.name === "AbortError") {
        return { features: [], source: "tiles", aborted: true };
      }
      rest(globalKey, err);
      return { features: [], source: null, aborted: false };
    }
  }

  return {
    features: collections.filter(Boolean).flat(),
    source: "tiles",
    aborted: false,
  };
}

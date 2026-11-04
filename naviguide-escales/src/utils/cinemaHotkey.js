/** Quitte le plein écran du document s'il est actif. Sans effet sinon. */
export function exitDocumentFullscreen(doc = typeof document !== "undefined" ? document : null) {
  if (!doc) return false;
  const el = doc.fullscreenElement || doc.webkitFullscreenElement;
  if (!el) return false;
  const exit = doc.exitFullscreen || doc.webkitExitFullscreen;
  if (typeof exit !== "function") return false;
  try {
    const result = exit.call(doc);
    if (result && typeof result.catch === "function") result.catch(() => {});
  } catch {
    return false;
  }
  return true;
}

/** Booléens show* des calques, pour les rendre après Stop. */
export function snapshotShowLayers(layers) {
  const saved = {};
  if (!layers || typeof layers !== "object") return saved;
  for (const [key, value] of Object.entries(layers)) {
    if (!key.startsWith("show") || typeof value !== "boolean") continue;
    saved[key] = value;
  }
  return saved;
}

export function restoreShowLayers(layers, saved) {
  if (!layers || !saved) return 0;
  let n = 0;
  for (const [key, value] of Object.entries(saved)) {
    if (typeof value !== "boolean") continue;
    const setterName = `set${key.charAt(0).toUpperCase()}${key.slice(1)}`;
    const setter = layers[setterName];
    if (typeof setter !== "function") continue;
    if (layers[key] === value) continue;
    setter(value);
    n += 1;
  }
  return n;
}

/** Touche C seule = Cinéma. ⌘C / Ctrl+C restent Copier. */
export function isCinemaKey(e) {
  if (!e || e.code !== "KeyC") return false;
  if (e.metaKey || e.ctrlKey) return false;
  if (e.altKey) return false;
  return true;
}

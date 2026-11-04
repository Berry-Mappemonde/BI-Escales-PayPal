// Readable names for the codes a Science record carries (`kind`).

const KIND_KEYS = {
  argo_float: "layerFicheKindArgoFloat",
  argo: "layerFicheKindArgoFloat",
  float: "layerFicheKindArgoFloat",
  dataset: "layerFicheKindDataset",
  cruise: "layerFicheKindCruise",
  mooring: "layerFicheKindMooring",
  buoy: "layerFicheKindBuoy",
  station: "layerFicheKindStation",
  coastline: "layerFicheKindCoastline",
  glider: "layerFicheKindGlider",
};

/**
 * Label of a Science `kind` in the reader's language (`t` = i18n lookup).
 * An unknown code is never shown raw: « sea_level_gauge » → « Sea level gauge ».
 */
export function scienceKindLabel(kind, t) {
  const code = String(kind || "").trim();
  if (!code) return "";
  const key = KIND_KEYS[code.toLowerCase()];
  if (key && typeof t === "function") {
    const label = t(key);
    if (label && label !== key) return label;
  }
  const words = code.replace(/[_-]+/g, " ").replace(/\s+/g, " ").trim().toLowerCase();
  return words ? words[0].toUpperCase() + words.slice(1) : "";
}

export const SCIENCE_KIND_KEYS = Object.freeze({ ...KIND_KEYS });

/** Source of a Science record (same rule as Blue Intelligence). */
export function scienceSourceOf(props = {}) {
  return props.source
    || (props.kind === "argo_float" ? "argo" : "")
    || (props.kind === "cruise" ? "csr" : "");
}

export function filterScienceFeatures(fc, source) {
  return {
    type: "FeatureCollection",
    features: (fc?.features || []).filter((f) => scienceSourceOf(f.properties || {}) === source),
  };
}

export const SCIENCE_CATALOG_SOURCES = ["sextant", "argo", "odatis", "edmed", "csr"];

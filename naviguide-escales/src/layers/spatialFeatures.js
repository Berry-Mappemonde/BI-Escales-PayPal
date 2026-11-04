export const POINT_RENDER_BUDGET = 420;

function mapBounds(bounds) {
  if (!bounds) return null;
  if (typeof bounds.getWest === "function") {
    return {
      west: bounds.getWest(),
      south: bounds.getSouth(),
      east: bounds.getEast(),
      north: bounds.getNorth(),
    };
  }
  return bounds;
}

/**
 * Bbox stable envoyée à l'API catalogue. Leaflet peut étendre la Mercator
 * au-delà des pôles à faible zoom : les latitudes HTTP restent géographiques.
 */
// What belongs to one point only: on a grouped cell it would read as if it
// were true for every point of the group.
const POINT_ONLY_PROPS = [
  "name", "title", "description", "website", "telephone", "url", "canal_vhf",
  "source_urls", "manager_url", "visit_url", "country", "region", "funder",
  "wmo", "ship", "email",
];

export function clusterProperties(properties) {
  const rest = { ...(properties || {}) };
  for (const key of POINT_ONLY_PROPS) delete rest[key];
  return rest;
}

export function quantizedCatalogBbox(rawBounds, zoom) {
  const bounds = mapBounds(rawBounds);
  if (!bounds) return null;
  const step = Math.max(0.25, 90 / (2 ** Math.max(0, Number(zoom || 2) - 2)));
  const floor = (value) => Math.floor(value / step) * step;
  const ceil = (value) => Math.ceil(value / step) * step;
  const clampLatitude = (value) => Math.max(-90, Math.min(90, value));
  return [
    floor(Number(bounds.west)),
    clampLatitude(floor(Number(bounds.south))),
    ceil(Number(bounds.east)),
    clampLatitude(ceil(Number(bounds.north))),
  ]
    .map((value) => value.toFixed(3))
    .join(",");
}

function visibleLongitude(lon, bounds) {
  const copies = [lon - 360, lon, lon + 360];
  if (bounds.west <= bounds.east) {
    return copies.find((value) => value >= bounds.west && value <= bounds.east);
  }
  return copies.find((value) => value >= bounds.west && value <= bounds.east + 360);
}

export function pointInBounds(lon, lat, rawBounds) {
  const bounds = mapBounds(rawBounds);
  if (!bounds || !Number.isFinite(lon) || !Number.isFinite(lat)) return false;
  if (lat < bounds.south || lat > bounds.north) return false;
  return visibleLongitude(lon, bounds) != null;
}

function lineTouchesBounds(coords, bounds) {
  return (coords || []).some((point) => (
    Array.isArray(point)
    && pointInBounds(Number(point[0]), Number(point[1]), bounds)
  ));
}

/**
 * Garde seulement les entités potentiellement visibles avant de créer
 * les objets Leaflet. Les tracés sont conservés dès qu’un sommet est visible.
 */
export function visibleFeatureCollection(fc, bounds) {
  return {
    type: "FeatureCollection",
    features: (fc?.features || []).flatMap((feature) => {
      const geometry = feature?.geometry || {};
      if (geometry.type === "Point") {
        const lon = Number(geometry.coordinates?.[0]);
        const lat = Number(geometry.coordinates?.[1]);
        const normalizedBounds = mapBounds(bounds);
        if (!normalizedBounds) return [];
        const copy = visibleLongitude(lon, normalizedBounds);
        if (copy == null || !pointInBounds(lon, lat, bounds)) return [];
        if (copy === lon) return [feature];
        return [{
          ...feature,
          geometry: { ...geometry, coordinates: [copy, lat] },
        }];
      }
      if (geometry.type === "LineString") return lineTouchesBounds(geometry.coordinates, bounds) ? [feature] : [];
      return [];
    }),
  };
}

/**
 * Agrège les points visibles dans des cellules écran quand le budget est dépassé.
 * Le clic sur une cellule garde son nombre d’entités dans `clusterCount`.
 */
export function aggregatePointFeatures(features, project, {
  budget = POINT_RENDER_BUDGET,
  minCellPx = 30,
} = {}) {
  const points = (features || []).filter((feature) => feature?.geometry?.type === "Point");
  if (points.length <= budget || typeof project !== "function") return points;
  const cellSize = minCellPx * Math.ceil(Math.sqrt(points.length / budget));
  const buckets = new Map();
  points.forEach((feature) => {
    const [lon, lat] = feature.geometry.coordinates || [];
    const point = project(lon, lat);
    if (!point || !Number.isFinite(point.x) || !Number.isFinite(point.y)) return;
    const key = `${Math.floor(point.x / cellSize)}:${Math.floor(point.y / cellSize)}`;
    const bucket = buckets.get(key) || {
      first: feature,
      count: 0,
      lon: 0,
      lat: 0,
    };
    bucket.count += 1;
    bucket.lon += lon;
    bucket.lat += lat;
    buckets.set(key, bucket);
  });
  return [...buckets.values()].map((bucket) => {
    if (bucket.count === 1) return bucket.first;
    return {
      type: "Feature",
      geometry: {
        type: "Point",
        coordinates: [bucket.lon / bucket.count, bucket.lat / bucket.count],
      },
      // No name here: the card names a cell by its count, through i18n.
      properties: {
        ...clusterProperties(bucket.first.properties),
        clusterCount: bucket.count,
      },
    };
  });
}

import { gebcoLookup } from "./gebco.js";

export const ICI_RADIUS_NM = 30;

export function emptyDossier(lat, lon) {
  return {
    version: 1,
    at: { lat, lon },
    radiusNm: ICI_RADIUS_NM,
    zee: null,
    poe: [],
    amp: [],
    projects: [],
    nearby: { marinas: [], capitaineries: [], wpi: [], anchorages: [] },
    marks: [],
    aton: { nearby: [], source: null, reason: null },
    science: null,
    satellites: null,
    weather: null,
    emodnet: null,
    review: null,
    polar: null,
    event: null,
    climatology: null,
    sources: {
      zee: null,
      bi: null,
      gebco: null,
      climatology: null,
      satellites: null,
      weather: null,
      emodnet: null,
      aton: null,
      anchorages: null,
      review: null,
    },
    depthOffshore: null,
  };
}

function polarFromMeta(polarMeta, jambe) {
  if (!polarMeta && !jambe) return null;
  const polar = {};
  if (polarMeta) {
    polar.boat = polarMeta.boat_name;
    polar.vmgHint = polarMeta.vmg_summary?.["12"] ?? null;
  }
  if (jambe) {
    if (jambe.speedKnots != null) polar.speedKnots = jambe.speedKnots;
    if (jambe.etaHours != null) polar.etaHours = jambe.etaHours;
  }
  return Object.keys(polar).length ? polar : null;
}

/** Merge the server bag with polar / leg / event — never the grid. */
export function mergeDossier(base, extras = {}) {
  const lat = base?.at?.lat ?? extras.lat ?? 0;
  const lon = base?.at?.lon ?? extras.lon ?? 0;
  const d = {
    ...emptyDossier(lat, lon),
    ...(base || {}),
    nearby: {
      ...emptyDossier(lat, lon).nearby,
      ...(base?.nearby || {}),
    },
    aton: {
      ...emptyDossier(lat, lon).aton,
      ...(base?.aton || {}),
    },
    sources: {
      ...emptyDossier(lat, lon).sources,
      ...(base?.sources || {}),
    },
  };
  const polar = polarFromMeta(extras.polarMeta, extras.jambe);
  if (polar) d.polar = polar;
  if (extras.weather) d.weather = extras.weather;
  if (extras.event) d.event = extras.event;
  if (extras.climatology) d.climatology = extras.climatology;
  if (extras.jambe) {
    d.marks = [{
      kind: "leg",
      from: extras.jambe.fromStop || null,
      to: extras.jambe.toStop || null,
      phase: extras.jambe.phase || null,
      vehicle: extras.jambe.vehicle || null,
    }];
  }
  if (d.polar && "grid" in d.polar) {
    const { grid: _grid, ...rest } = d.polar;
    d.polar = rest;
  }
  if (extras.depthOffshore !== undefined) {
    d.depthOffshore = extras.depthOffshore;
  } else if (extras.gebcoGrid !== undefined || extras.distToShoreNm != null) {
    d.depthOffshore = gebcoLookup(lat, lon, {
      grid: extras.gebcoGrid,
      distToShoreNm: extras.distToShoreNm,
    });
  } else {
    d.depthOffshore = base?.depthOffshore ?? gebcoLookup(lat, lon, {
      grid: extras.gebcoGrid,
      distToShoreNm: extras.distToShoreNm,
    });
  }
  return d;
}

export function ici(lat, lon, extras = {}) {
  return mergeDossier(emptyDossier(lat, lon), extras);
}

/** Boat position (not the plane) to fill the bag. */
export function boatPositionFromCast(cast, snappedPosition) {
  if (cast?.vehicle === "plane" && cast.main) {
    return { lat: cast.main.lat, lon: cast.main.lon };
  }
  if (cast?.vehicle === "side" && cast.side) {
    return { lat: cast.side.lat, lon: cast.side.lon };
  }
  if (cast?.main && Number.isFinite(cast.main.lat) && Number.isFinite(cast.main.lon)) {
    return { lat: cast.main.lat, lon: cast.main.lon };
  }
  if (Array.isArray(snappedPosition) && snappedPosition.length >= 2) {
    return { lat: snappedPosition[1], lon: snappedPosition[0] };
  }
  return null;
}

export function zeeEnterEvent(prevMrgid, zee) {
  const mrgid = zee?.mrgid ?? null;
  if (prevMrgid === undefined) return null;
  if (mrgid === prevMrgid) return null;
  if (!zee) return null;
  return { type: "zee-enter", name: zee.name, mrgid };
}

/**
 * Export GeoJSON / KML de la route de la vue.
 * Port allégé de naviguide/naviguide-app/src/components/ExportSidebar.jsx
 * (downloadFile, buildGeoJSON, buildKML).
 */
import { isAirSegment, legKind } from "./berryLegs.js";
import { haversineNm, wrapLon, wrapLonParts } from "./geo.js";

const KIND = { mer: "mer", terre: "terre", air: "air" };

export function viewExportMode(drawingMode, isSuivre) {
  if (drawingMode) return "tracer";
  if (isSuivre) return "suivre";
  return "simulation";
}

export function exportFilename(mode, ext, when = new Date()) {
  const yyyy = when.getFullYear();
  const mm = String(when.getMonth() + 1).padStart(2, "0");
  const dd = String(when.getDate()).padStart(2, "0");
  const slug = viewExportMode(mode === "tracer" || mode === "draw" || mode === "drawn", mode === "suivre" || mode === "follow");
  const suffix = String(ext || "").replace(/^\./, "");
  return `naviguide-${slug}-${yyyy}-${mm}-${dd}.${suffix}`;
}

function lonLat(coord) {
  if (!Array.isArray(coord) || coord.length < 2) return null;
  const lon = Number(coord[0]);
  const lat = Number(coord[1]);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
  if (Math.abs(lat) > 90 || Math.abs(lon) > 540) return null;
  return [lon, lat];
}

function lineCoords(seg) {
  return (seg?.coords || []).map(lonLat).filter(Boolean);
}

export function isEscalePoint(point) {
  if (!point) return false;
  const lat = Number(point.lat);
  const lon = Number(point.lon);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return false;
  if (point.point_type === "intermediate") return false;
  if (point.point_type === "escale") return true;
  if (point.flag === "" || point.flag === false) return false;
  return true;
}

export function canExportRoute(segments, points) {
  const hasLine = (segments || []).some((seg) => lineCoords(seg).length >= 2);
  const hasPoint = (points || []).some(isEscalePoint);
  return hasLine || hasPoint;
}

function endOf(side, fallback) {
  if (side?.name) {
    return { name: side.name, lat: side.lat, lon: side.lon, country: side.country || side.pays || "" };
  }
  if (fallback) {
    return {
      name: fallback.name || "",
      lat: fallback.lat,
      lon: fallback.lon,
      country: fallback.country || fallback.pays || "",
    };
  }
  return { name: side?.name || "", lat: side?.lat, lon: side?.lon, country: side?.country || side?.pays || "" };
}

function kindOf(seg) {
  const raw = String(seg?.kind || seg?.type || "").toLowerCase();
  if (raw === "air") return KIND.air;
  if (raw === "mer" || raw === "sea" || raw === "maritime") return KIND.mer;
  if (raw === "terre" || raw === "land" || raw === "overland") return KIND.terre;
  if (isAirSegment(seg)) return KIND.air;
  if (seg?.nonMaritime) return KIND.terre;
  const inferred = legKind(seg?.from?.name, seg?.to?.name);
  if (inferred === "air") return KIND.air;
  if (inferred === "land") return KIND.terre;
  return KIND.mer;
}

function nmOf(seg, coords) {
  if (Number.isFinite(seg?.nm)) return Math.round(Number(seg.nm) * 10) / 10;
  let nm = 0;
  for (let i = 0; i < coords.length - 1; i += 1) {
    nm += haversineNm(coords[i][1], coords[i][0], coords[i + 1][1], coords[i + 1][0]);
  }
  return Math.round(nm * 10) / 10;
}

function interpolate(a, b, t) {
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
}

/** Découpe une LineString en tirets (KML n'a pas de dash natif). */
export function dashChunks(coords, dashNm = 40, gapNm = 24) {
  if (!coords || coords.length < 2) return [];
  let total = 0;
  for (let i = 0; i < coords.length - 1; i += 1) {
    total += haversineNm(coords[i][1], coords[i][0], coords[i + 1][1], coords[i + 1][0]);
  }
  if (total < dashNm * 2) return [coords];
  const chunks = [];
  let phase = "dash";
  let phaseLeft = dashNm;
  let current = [coords[0]];
  for (let i = 0; i < coords.length - 1; i += 1) {
    let a = coords[i];
    const b = coords[i + 1];
    let remain = haversineNm(a[1], a[0], b[1], b[0]);
    while (remain > 1e-6) {
      const step = Math.min(remain, phaseLeft);
      const t = remain > 0 ? step / remain : 1;
      const next = interpolate(a, b, t);
      if (phase === "dash") current.push(next);
      a = next;
      remain -= step;
      phaseLeft -= step;
      if (phaseLeft <= 1e-9) {
        if (phase === "dash") {
          if (current.length >= 2) chunks.push(current);
          current = [];
          phase = "gap";
          phaseLeft = gapNm;
        } else {
          phase = "dash";
          phaseLeft = dashNm;
          current = [a];
        }
      }
    }
  }
  if (phase === "dash" && current.length >= 2) chunks.push(current);
  return chunks.length ? chunks : [coords];
}

function escapeXml(value) {
  return String(value ?? "")
    .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g, "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/** GeoJSON (RFC 7946) : lon dans [−180, 180], coupée à l'antiméridien. */
function lineGeometry(coords) {
  const parts = wrapLonParts(coords);
  if (parts.length <= 1) return { type: "LineString", coordinates: parts[0] || coords.map(([lon, lat]) => [wrapLon(lon), lat]) };
  return { type: "MultiLineString", coordinates: parts };
}

function kmlCoords(coords) {
  return coords.map(([lon, lat]) => `${lon},${lat},0`).join(" ");
}

export function buildGeoJSON(segments, points, name = "naviguide") {
  const features = [];
  const stops = points || [];

  (segments || []).forEach((seg, index) => {
    const coords = lineCoords(seg);
    if (coords.length < 2) return;
    const from = endOf(seg.from, stops[index]);
    const to = endOf(seg.to, stops[index + 1]);
    features.push({
      type: "Feature",
      properties: {
        from: from.name || "",
        to: to.name || "",
        nm: nmOf(seg, coords),
        kind: kindOf({ ...seg, from, to }),
      },
      geometry: lineGeometry(coords),
    });
  });

  stops.filter(isEscalePoint).forEach((point) => {
    features.push({
      type: "Feature",
      properties: {
        name: point.name || "",
        country: point.country || point.pays || "",
      },
      geometry: { type: "Point", coordinates: [wrapLon(Number(point.lon)), Number(point.lat)] },
    });
  });

  return {
    type: "FeatureCollection",
    name,
    features,
  };
}

export function buildKML(segments, points, name = "naviguide") {
  const stops = points || [];
  const routePlacemarks = (segments || []).map((seg, index) => {
    const coords = lineCoords(seg);
    if (coords.length < 2) return "";
    const from = endOf(seg.from, stops[index]);
    const to = endOf(seg.to, stops[index + 1]);
    const kind = kindOf({ ...seg, from, to });
    const nm = nmOf(seg, coords);
    const label = escapeXml(`${from.name || "?"} → ${to.name || "?"}`);
    const style = kind === KIND.air ? "#air-style" : kind === KIND.terre ? "#overland-style" : "#maritime-style";
    // KML : longitudes dans [−180, 180], une ligne par côté de l'antiméridien.
    const lines = (kind === KIND.air ? dashChunks(coords) : [coords]).flatMap((line) => wrapLonParts(line));
    const geometry = lines.length === 1
      ? `      <LineString>
        <tessellate>1</tessellate>
        <coordinates>${kmlCoords(lines[0])}</coordinates>
      </LineString>`
      : `      <MultiGeometry>
${lines.map((chunk) => `        <LineString><tessellate>1</tessellate><coordinates>${kmlCoords(chunk)}</coordinates></LineString>`).join("\n")}
      </MultiGeometry>`;
    return `    <Placemark>
      <name>${label}</name>
      <styleUrl>${style}</styleUrl>
      <ExtendedData>
        <Data name="kind"><value>${kind}</value></Data>
        <Data name="nm"><value>${nm}</value></Data>
      </ExtendedData>
${geometry}
    </Placemark>`;
  }).filter(Boolean).join("\n");

  const waypointPlacemarks = stops.filter(isEscalePoint).map((point) => {
    const label = escapeXml(point.name || "");
    const country = escapeXml(point.country || point.pays || "");
    return `    <Placemark>
      <name>${label}</name>
      <styleUrl>#escale-style</styleUrl>
      <ExtendedData>
        <Data name="country"><value>${country}</value></Data>
      </ExtendedData>
      <Point>
        <coordinates>${wrapLon(Number(point.lon))},${Number(point.lat)},0</coordinates>
      </Point>
    </Placemark>`;
  }).join("\n");

  return `<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>${escapeXml(name)}</name>
    <Style id="maritime-style">
      <LineStyle><color>ffff7700</color><width>3</width></LineStyle>
    </Style>
    <Style id="overland-style">
      <LineStyle><color>ff888888</color><width>2</width></LineStyle>
    </Style>
    <Style id="air-style">
      <LineStyle><color>ff111111</color><width>2.5</width></LineStyle>
    </Style>
    <Style id="escale-style">
      <IconStyle>
        <scale>1.1</scale>
        <Icon><href>https://maps.google.com/mapfiles/kml/paddle/blu-circle.png</href></Icon>
        <hotSpot x="0.5" y="0" xunits="fraction" yunits="fraction"/>
      </IconStyle>
    </Style>
    <Folder>
      <name>Routes</name>
${routePlacemarks}
    </Folder>
    <Folder>
      <name>Escales</name>
${waypointPlacemarks}
    </Folder>
  </Document>
</kml>`;
}

export function downloadFile(content, filename, mimeType, doc = typeof document !== "undefined" ? document : null) {
  if (!doc?.createElement || typeof Blob === "undefined" || typeof URL === "undefined") return false;
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = doc.createElement("a");
  a.href = url;
  a.download = filename;
  doc.body?.appendChild(a);
  a.click();
  doc.body?.removeChild(a);
  URL.revokeObjectURL(url);
  return true;
}

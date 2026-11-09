import { drawingPinHtml } from "../../../../naviguide-escales/src/utils/waypointFlags.js";

export function escapeAttr(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;");
}

const FLAG_IMG_STYLE =
  "height:22px;width:auto;display:block;box-sizing:border-box;border:1px solid var(--color-line);border-radius:var(--radius-chip);box-shadow:var(--shadow-marker)";

/**
 * Leaflet divIcon HTML for a voyage stop: flag stack or drawing pin, with stop name for assistive tech.
 * @param {{ name?: string; flags?: string[] }} stop
 */
export function stopMarkerIconHtml(stop) {
  const label = escapeAttr(stop?.name || "");
  const srcs = stop?.flags || [];
  if (srcs.length) {
    const imgs = srcs
      .map((src) => `<img src="${src}" alt="" style="${FLAG_IMG_STYLE}" />`)
      .join("");
    return `<div class="flag-stack" role="img" aria-label="${label}">${imgs}</div>`;
  }
  const aria = label ? ` role="img" aria-label="${label}"` : "";
  return drawingPinHtml(0, aria);
}

export function stopMarkerIconSize(stop) {
  const srcs = stop?.flags || [];
  if (srcs.length) {
    return { iconSize: [22 * srcs.length, 24], iconAnchor: [11 * srcs.length, 12] };
  }
  return { iconSize: [14, 14], iconAnchor: [7, 7] };
}

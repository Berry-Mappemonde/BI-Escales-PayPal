import type { TFunction } from "i18next";
import type { ScheduleResponse } from "../api/types";
import { stopOnSchedule } from "../components/captain/captainEvidence";
import { placeSlugFromUrl } from "../marinas/marinaPlaceLink.js";

const RAW_SLUG_RE = /^(dep-|leg-|projet-|project-)/i;
const OSM_ID_RE = /^(way|node|relation)\//i;

export type MilestoneLabelStop = { milestoneId?: string; name?: string };

export function looksLikeRawMilestoneId(value: string): boolean {
  const token = String(value || "").trim();
  return Boolean(token && (RAW_SLUG_RE.test(token) || OSM_ID_RE.test(token)));
}

/** Human stop/leg label for UI; never show dep-* slugs when a name is unknown. */
export function milestoneDisplayName(
  milestoneId: string,
  schedule: ScheduleResponse | null | undefined,
  stops?: MilestoneLabelStop[] | null,
  t?: TFunction,
): string {
  const id = String(milestoneId || "").trim();
  if (!id) return t?.("display.unknownStop") ?? "—";
  const fromSchedule = stopOnSchedule(schedule ?? null, id);
  if (fromSchedule.name?.trim()) return fromSchedule.name.trim();
  const fromStop = (stops || []).find((row) => row.milestoneId === id);
  if (fromStop?.name?.trim()) return fromStop.name.trim();
  if (looksLikeRawMilestoneId(id)) return t?.("display.unknownStop") ?? "Stop";
  return id;
}

export function marinaDisplayName(
  props: { name?: string; osm_id?: string; id?: string } | null | undefined,
  t: TFunction,
): string {
  const name = String(props?.name || "").trim();
  if (name) return name;
  return t("marinas.unnamed");
}

/** Link text for a Google /place/ URL — place title, not the encoded slug alone. */
export function googleMapsLinkLabel(url: string | null | undefined, t: TFunction): string {
  const slug = placeSlugFromUrl(String(url || ""));
  if (slug && !OSM_ID_RE.test(slug) && !RAW_SLUG_RE.test(slug)) {
    return slug.replace(/\+/g, " ");
  }
  return t("sheet.marina.maps");
}

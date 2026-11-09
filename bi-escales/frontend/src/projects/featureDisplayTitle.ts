import type { TFunction } from "i18next";

type FeatureProps = {
  id?: string;
  title?: string;
  title_en?: string;
  project_kind?: string;
};

/** Localized list title for gear seed rows (FR titles from API; EN via i18n keys). */
export function featureDisplayTitle(
  props: FeatureProps | null | undefined,
  language: string,
  t: TFunction,
): string {
  const raw = props || {};
  const id = String(raw.id || "").trim();
  const fallback = String(raw.title || raw.id || "");
  const isGear = String(raw.project_kind || "") === "gear_project";
  if (!isGear || !id) return fallback;

  const enFromApi = String(raw.title_en || "").trim();
  if (language.toLowerCase().startsWith("en") && enFromApi) return enFromApi;

  const key = `gear.seedTitles.${id}`;
  const localized = t(key, { defaultValue: "" });
  if (localized && localized !== key) return localized;

  return fallback;
}

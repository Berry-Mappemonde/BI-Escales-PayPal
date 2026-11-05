export type Lang = "fr" | "en";

const LOCALE: Record<Lang, string> = { fr: "fr-FR", en: "en-GB" };

export function formatDay(iso: string, lang: Lang): string {
  return new Intl.DateTimeFormat(LOCALE[lang], {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  }).format(new Date(iso));
}

export function formatDayTime(iso: string, lang: Lang): string {
  return new Intl.DateTimeFormat(LOCALE[lang], {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
  }).format(new Date(iso));
}

export function formatEur(amount: number, lang: Lang): string {
  return new Intl.NumberFormat(LOCALE[lang], {
    style: "currency",
    currency: "EUR",
    maximumFractionDigits: 0,
  }).format(amount);
}

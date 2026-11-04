import { useEffect, useState } from "react";
import { useLang } from "../i18n/LangContext.jsx";
import {
  formatDepartureDate,
  normalizeUtcTime,
  parseDepartureUtc,
  parseFrenchDepartureDate,
  splitDepartureUtc,
} from "../engine/voyageClock.js";

export function DepartureField({
  t0,
  onT0,
  compact = false,
  testId = "departure-field",
  disabled = false,
}) {
  const { t } = useLang();
  const { date, time } = splitDepartureUtc(t0);
  const [dateValue, setDateValue] = useState(() => formatDepartureDate(date));
  const [timeValue, setTimeValue] = useState(time);

  useEffect(() => {
    setDateValue(formatDepartureDate(date));
    setTimeValue(time);
  }, [date, time]);

  const setDate = (nextDate) => {
    setDateValue(nextDate);
    const parsedDate = parseFrenchDepartureDate(nextDate);
    if (parsedDate) onT0?.(parseDepartureUtc(parsedDate, normalizeUtcTime(timeValue) || time));
  };
  const setTime = (nextTime) => {
    setTimeValue(nextTime);
    const parsedTime = normalizeUtcTime(nextTime);
    if (parsedTime) onT0?.(parseDepartureUtc(parseFrenchDepartureDate(dateValue) || date, parsedTime));
  };

  const inputClass = compact
    ? "h-5 min-w-0 bg-transparent border-0 p-0 text-[9px] text-white tabular-nums disabled:opacity-40"
    : "h-5 min-w-0 w-full bg-slate-900/80 border border-white/10 rounded px-1 text-[10px] text-white tabular-nums disabled:opacity-40";

  return (
    <div
      data-testid={testId}
      aria-disabled={disabled || undefined}
      className={compact
        ? "naviguide-departure-field h-6 rounded-md border border-white/10 bg-slate-800/50 px-1 inline-flex items-center w-max"
        : "naviguide-departure-field h-[46px] rounded-lg border border-white/10 bg-slate-800/50 px-2 py-1"}
    >
      {compact ? (
        <span className="sr-only">{t("departureTitle")}</span>
      ) : (
        <div className="text-[9px] font-semibold uppercase tracking-wider text-slate-400">
          {t("departureTitle")}
        </div>
      )}
      <div className={compact ? "flex items-center gap-[1ch] w-max" : "grid grid-cols-[1.35fr_0.85fr] gap-1 mt-0.5"}>
        <label className="flex items-center gap-1 min-w-0">
          {compact ? null : <span className="text-[8px] text-slate-500 whitespace-nowrap">{t("departureDate")}</span>}
          <input
            name="departure-date"
            type="text"
            inputMode="numeric"
            autoComplete="off"
            placeholder={t("departureDateFormat")}
            value={dateValue}
            disabled={disabled}
            onChange={(e) => setDate(e.target.value)}
            aria-label={t("departureDate")}
            aria-invalid={dateValue !== "" && !parseFrenchDepartureDate(dateValue)}
            className={compact ? `${inputClass} w-[10ch]` : inputClass}
          />
        </label>
        <label className="flex items-center gap-1 min-w-0">
          {compact ? null : <span className="text-[8px] text-slate-500 whitespace-nowrap">{t("departureTimeUtc")}</span>}
          <input
            name="departure-time-utc"
            type="text"
            inputMode="numeric"
            autoComplete="off"
            placeholder="HH:MM"
            value={timeValue}
            disabled={disabled}
            onChange={(e) => setTime(e.target.value)}
            aria-label={t("departureTimeUtc")}
            aria-invalid={timeValue !== "" && !normalizeUtcTime(timeValue)}
            className={compact ? `${inputClass} w-[5ch]` : inputClass}
          />
        </label>
      </div>
    </div>
  );
}

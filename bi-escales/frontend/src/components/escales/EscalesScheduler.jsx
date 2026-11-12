/**
 * Calendrier des escales, liste locale.
 * Composant isolé : le frontend parent fournit `schedule`.
 * Nettoyage calendrier : PR #27 chore/ui-audit (libellés morts retirés).
 * Lot 2 (plan canvas P2) : boutons de planification seulement si `planningEnabled` (Bryntum).
 */
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { PledgeButton } from "../PledgeButton";
import BryntumTimeline from "./BryntumTimeline.jsx";
import { formatEurAmount } from "../../voyage/stopStatus.js";

function toDate(value) {
  if (!value) return null;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function withoutStoragePrefix(value) {
  return String(value || "").replace(/^dep-/i, "");
}

function shownEscaleName(row) {
  const named = row.display_name || row.name || row.title || "";
  if (named && !/^dep-/i.test(String(named))) return named;
  return withoutStoragePrefix(row.milestone_id || named);
}

const DAY_MS = 24 * 60 * 60 * 1000;

/** The leg that leaves this stop: its departure is when the boat's stay ends. */
function legLeaving(row, legs) {
  const slug = String(row.slug || withoutStoragePrefix(row.milestone_id) || "").trim();
  return (legs || []).find(
    (leg) => (slug && leg.from_slug === slug) || (row.name && leg.from_name === row.name),
  );
}

/**
 * One bar per stop, from arrival to departure: how long the boat stays.
 * The departure is the schedule's (the leg that leaves the stop). A stop with no
 * known departure, or one the boat leaves within the day, is drawn one day wide so
 * that it stays visible; `departureKnown` says which case it is.
 */
function buildEvents(escales, legs) {
  return (escales || []).map((row, index) => {
    const start = toDate(row.arrival_iso) || new Date();
    const departure = toDate(row.departure_iso) || toDate(legLeaving(row, legs)?.departure_iso);
    const departureKnown = Boolean(departure && departure.getTime() >= start.getTime());
    const minEnd = new Date(start.getTime() + DAY_MS);
    const end = departureKnown && departure.getTime() > minEnd.getTime() ? departure : minEnd;
    return {
      id: row.milestone_id || row.slug || `escale-${index}`,
      name: shownEscaleName(row),
      startDate: start,
      endDate: end,
      departureDate: departureKnown ? departure : null,
      milestoneId: row.milestone_id,
      lat: row.lat,
      lon: row.lon,
    };
  });
}

function cabinAmount(prices) {
  const row = (prices?.prices || []).find((item) => item.kind === "cabin_leg");
  return row?.amount_eur || "80.00";
}

function LegList({ legs, amount, onAuthorized }) {
  const { t } = useTranslation();
  if (!legs?.length) return null;
  return (
    <ul className="escales-legs" data-testid="schedule-legs">
      {legs.map((leg) => (
        <li key={leg.id} data-testid="schedule-leg" data-leg={leg.id}>
          <span>
            {t("scheduler.cabinLeg", { from: leg.from_name, to: leg.to_name })}
            {" "}
            <span data-testid="cabin-price">{t("scheduler.cabinPrice", { amount })}</span>
          </span>
          <PledgeButton
            values={{
              amount_eur: amount,
              description: t("scheduler.cabinDescription", { from: leg.from_name, to: leg.to_name }),
              milestone_id: leg.id,
              kind: "cabin_leg",
            }}
            onAuthorized={onAuthorized}
          />
        </li>
      ))}
    </ul>
  );
}

function LocalScheduleList({ events, onSelect }) {
  const { t } = useTranslation();
  if (!events.length) {
    return <p className="escales-scheduler-empty">{t("scheduler.empty")}</p>;
  }
  return (
    <ul className="escales-scheduler-list">
      {events.map((event) => (
        <li key={event.id}>
          <button type="button" onClick={() => onSelect?.(event)}>
            <strong>{event.name}</strong>
            <span>
              {event.startDate.toISOString().slice(0, 10)}
              {event.departureDate ? ` → ${event.departureDate.toISOString().slice(0, 10)}` : ""}
            </span>
            {event.milestoneId ? (
              <code>{withoutStoragePrefix(event.milestoneId)}</code>
            ) : null}
            {event.statusLabel ? <span data-testid="schedule-stop-status">{event.statusLabel}</span> : null}
            {event.pledgesLabel ? <span data-testid="schedule-stop-pledges">{event.pledgesLabel}</span> : null}
          </button>
        </li>
      ))}
    </ul>
  );
}

export default function EscalesScheduler({
  schedule,
  onSelectEscale,
  onAuthorized,
  planningEnabled = false,
  showCabins = true,
  wide = false,
  // Treasurer only: by milestone id, whether the boat has arrived and the held pledges there.
  stopOverview = /** @type {Record<string, { status: string | null, held: number, heldEur: number, due: boolean }> | null} */ (null),
}) {
  const { t, i18n } = useTranslation();
  const escales = schedule?.export?.escales || schedule?.escales || localFallbackEscales();
  const legs = schedule?.legs || [];
  const lang = i18n.language?.startsWith("en") ? "en" : "fr";
  // With the treasurer's overview, each stop also says its status and its held pledges, in words.
  const events = useMemo(() => {
    const base = buildEvents(escales, legs);
    if (!stopOverview) return base;
    return base.map((event) => {
      const row = stopOverview[event.milestoneId];
      if (!row) return { ...event, statusLabel: "", pledgesLabel: "" };
      const amount = formatEurAmount(row.heldEur, lang);
      return {
        ...event,
        statusLabel: row.status ? t(`stopPanel.status.${row.status}`) : "",
        pledgesLabel: row.held
          ? t(row.due ? "scheduler.pledgesDue" : "scheduler.pledgesHeld", { count: row.held, amount })
          : t("scheduler.pledgesNone"),
      };
    });
  }, [escales, legs, stopOverview, lang, t]);
  const extraColumns = useMemo(
    () =>
      stopOverview
        ? [
            { text: t("scheduler.colStatus"), field: "statusLabel", width: 110 },
            { text: t("scheduler.colPledges"), field: "pledgesLabel", width: 230 },
          ]
        : [],
    [stopOverview, t],
  );
  // The cabin checkouts are mounted only once the visitor asks for them: one PayPal
  // checkout per leg is a long list, and the calendar is the point of this section.
  const [cabinsOpen, setCabinsOpen] = useState(false);

  if (!planningEnabled) {
    return null;
  }

  return (
    <section className="escales-scheduler panel" data-source={schedule?.source || "local"}>
      <header>
        <h2>{t("scheduler.heading")}</h2>
      </header>
      <p className="hint escales-scheduler-lead">
        {t("scheduler.lead")}
        {onSelectEscale ? ` ${t("scheduler.leadSelect")}` : ""}
        {stopOverview ? ` ${t("scheduler.leadTreasurer")}` : ""}
      </p>
      <BryntumTimeline
        events={events}
        onSelect={onSelectEscale}
        fallback={<LocalScheduleList events={events} onSelect={onSelectEscale} />}
        extraColumns={extraColumns}
        // On a wide surface every stop's name and row fits; in the rail the list scrolls.
        {...(wide ? { nameWidth: 220, maxHeight: Number.POSITIVE_INFINITY } : {})}
      />
      {showCabins && legs.length ? (
        <details
          className="project-disclosure escales-cabins"
          data-testid="schedule-cabins"
          onToggle={(event) => setCabinsOpen(event.currentTarget.open)}
        >
          <summary className="project-summary">
            <h3>{t("scheduler.cabins")}</h3>
            <span aria-hidden="true">·</span>
            <span className="project-list-total" data-testid="schedule-cabins-count">{legs.length}</span>
            <svg viewBox="0 0 16 16" width="16" height="16" fill="none" aria-hidden="true"><path d="m5 6 3 3 3-3" stroke="currentColor" strokeWidth="1.5" /></svg>
          </summary>
          {cabinsOpen ? (
            <LegList legs={legs} amount={cabinAmount(schedule?.prices)} onAuthorized={onAuthorized} />
          ) : null}
        </details>
      ) : null}
    </section>
  );
}

export function localFallbackEscales() {
  return [];
}

export { buildEvents, LocalScheduleList, shownEscaleName, withoutStoragePrefix };

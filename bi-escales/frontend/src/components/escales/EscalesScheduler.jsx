/**
 * Calendrier des escales, liste locale.
 * Composant isolé : le frontend parent fournit `schedule`.
 * Nettoyage calendrier : PR #27 chore/ui-audit (libellés morts retirés).
 */
import { useMemo } from "react";
import { PledgeButton } from "../PledgeButton";

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

function buildEvents(escales) {
  return (escales || []).map((row, index) => {
    const start = toDate(row.arrival_iso) || new Date();
    const end = new Date(start.getTime() + 24 * 60 * 60 * 1000);
    return {
      id: row.milestone_id || row.slug || `escale-${index}`,
      name: shownEscaleName(row),
      startDate: start,
      endDate: end,
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
  if (!legs?.length) return null;
  return (
    <ul className="escales-legs" data-testid="schedule-legs">
      {legs.map((leg) => (
        <li key={leg.id} data-testid="schedule-leg" data-leg={leg.id}>
          <span>
            {leg.from_name} → {leg.to_name}
            {" "}
            <span data-testid="cabin-price">{amount} EUR</span>
          </span>
          <PledgeButton
            values={{
              amount_eur: amount,
              description: `Cabine ${leg.from_name} → ${leg.to_name}`,
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
  if (!events.length) {
    return <p className="escales-scheduler-empty">Aucune escale planifiée.</p>;
  }
  return (
    <ul className="escales-scheduler-list">
      {events.map((event) => (
        <li key={event.id}>
          <button type="button" onClick={() => onSelect?.(event)}>
            <strong>{event.name}</strong>
            <span>{event.startDate.toISOString().slice(0, 10)}</span>
            {event.milestoneId ? <code>{withoutStoragePrefix(event.milestoneId)}</code> : null}
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
}) {
  const escales = schedule?.export?.escales || schedule?.escales || localFallbackEscales();
  const events = useMemo(() => buildEvents(escales), [escales]);
  const legs = schedule?.legs || [];

  return (
    <section className="escales-scheduler" data-source={schedule?.source || "local"}>
      <header>
        <h2>Calendrier des escales</h2>
      </header>
      <LegList legs={legs} amount={cabinAmount(schedule?.prices)} onAuthorized={onAuthorized} />
      <LocalScheduleList events={events} onSelect={onSelectEscale} />
    </section>
  );
}

export function localFallbackEscales() {
  return [];
}

export { buildEvents, LocalScheduleList, shownEscaleName, withoutStoragePrefix };

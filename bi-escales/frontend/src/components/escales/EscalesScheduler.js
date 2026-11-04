/**
 * Calendrier des escales — Bryntum optionnel (ESCALES_BRYNTUM_ENABLED côté API).
 * Composant isolé : le frontend parent fournit `schedule` et `features`.
 */
import React, { useMemo } from "react";
import { advisoryView } from "./advisoryLabel.js";

export function AdvisoryBadge({ llmProposal }) {
  const view = advisoryView(llmProposal);
  if (!view) return null;
  return (
    <p className="escales-advisory" data-advisory="true" data-dropped={view.dropped ? "true" : "false"}>
      <strong>Advisory</strong>
      {view.dropped ? (
        <span> La suggestion du modèle est écartée. {view.reason}</span>
      ) : (
        <span> Suggestion du modèle, non exécutée : {view.proposal}. {view.reason}</span>
      )}
    </p>
  );
}

function toDate(value) {
  if (!value) return null;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function buildEvents(escales) {
  return (escales || []).map((row, index) => {
    const start = toDate(row.arrival_iso) || new Date();
    const end = new Date(start.getTime() + 24 * 60 * 60 * 1000);
    return {
      id: row.milestone_id || row.slug || `escale-${index}`,
      name: row.name || row.title || row.milestone_id,
      startDate: start,
      endDate: end,
      milestoneId: row.milestone_id,
      lat: row.lat,
      lon: row.lon,
    };
  });
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
            {event.milestoneId ? <code>{event.milestoneId}</code> : null}
          </button>
        </li>
      ))}
    </ul>
  );
}

function BryntumSchedule({ events, onSelect }) {
  const [Scheduler, setScheduler] = React.useState(null);
  const [error, setError] = React.useState(null);

  React.useEffect(() => {
    let cancelled = false;
    import("@bryntum/scheduler")
      .then((mod) => {
        if (!cancelled) setScheduler(() => mod.default || mod.Scheduler);
      })
      .catch((err) => {
        if (!cancelled) setError(err);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const containerRef = React.useRef(null);

  React.useEffect(() => {
    if (!Scheduler || !containerRef.current) return undefined;
    const instance = new Scheduler({
      appendTo: containerRef.current,
      startDate: events[0]?.startDate || new Date(),
      endDate: events[events.length - 1]?.endDate || new Date(),
      viewPreset: "weekAndDay",
      columns: [{ text: "Escale", field: "name", width: 220 }],
      resources: [{ id: "route", name: "Route officielle" }],
      events: events.map((event) => ({
        id: event.id,
        name: event.name,
        resourceId: "route",
        startDate: event.startDate,
        endDate: event.endDate,
        milestoneId: event.milestoneId,
      })),
      listeners: {
        eventClick({ eventRecord }) {
          onSelect?.({
            id: eventRecord.id,
            name: eventRecord.name,
            milestoneId: eventRecord.milestoneId,
            startDate: eventRecord.startDate,
            endDate: eventRecord.endDate,
          });
        },
      },
    });
    return () => instance.destroy();
  }, [Scheduler, events, onSelect]);

  if (error) {
    return <LocalScheduleList events={events} onSelect={onSelect} />;
  }
  if (!Scheduler) {
    return <p className="escales-scheduler-loading">Chargement du calendrier…</p>;
  }
  return <div className="escales-scheduler-bryntum" ref={containerRef} />;
}

export default function EscalesScheduler({ schedule, features, onSelectEscale, captainReview = null }) {
  const escales = schedule?.export?.escales || schedule?.escales || localFallbackEscales();
  const events = useMemo(() => buildEvents(escales), [escales]);
  const useBryntum = Boolean(features?.bryntum);

  return (
    <section className="escales-scheduler" data-source={schedule?.source || "local"}>
      <header>
        <h2>Calendrier des escales</h2>
        <p>Mode {useBryntum ? "Bryntum" : "local"} — Pay Only If We Sail</p>
      </header>
      <AdvisoryBadge llmProposal={captainReview?.llm_proposal} />
      {useBryntum ? (
        <BryntumSchedule events={events} onSelect={onSelectEscale} />
      ) : (
        <LocalScheduleList events={events} onSelect={onSelectEscale} />
      )}
    </section>
  );
}

export function localFallbackEscales() {
  return [
    {
      milestone_id: "dep-mayotte",
      name: "Mayotte",
      arrival_iso: "2026-09-01T08:00:00Z",
    },
    {
      milestone_id: "dep-fort-de-france",
      name: "Fort-de-France",
      arrival_iso: "2026-08-15T08:00:00Z",
    },
  ];
}

export { buildEvents, LocalScheduleList };

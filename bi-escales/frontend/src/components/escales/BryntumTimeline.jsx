/**
 * Timeline Bryntum (essai npm public @bryntum/scheduler-trial).
 * Import dynamique : retirer ce fichier + la dépendance optionnelle pour désactiver le partenaire.
 */
import React from "react";

function LocalScheduleList({ events, onSelect }) {
  if (!events.length) {
    return <p className="escales-scheduler-empty">Aucune escale planifiée.</p>;
  }
  return (
    <ul className="escales-scheduler-list" data-testid="escales-scheduler-local">
      {events.map((event) => (
        <li key={event.id}>
          <button type="button" onClick={() => onSelect?.(event)}>
            <strong>{event.name}</strong>
            <span>{event.startDate.toISOString().slice(0, 10)}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}

export default function BryntumTimeline({ events, onSelect }) {
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
    if (!Scheduler || !containerRef.current || !events.length) return undefined;
    const instance = new Scheduler({
      appendTo: containerRef.current,
      readOnly: true,
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
    return <p className="escales-scheduler-loading" data-testid="bryntum-loading">Chargement du calendrier…</p>;
  }
  return <div className="escales-scheduler-bryntum" data-testid="escales-scheduler-bryntum" ref={containerRef} />;
}

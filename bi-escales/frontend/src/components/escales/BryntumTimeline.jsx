/**
 * Bryntum Scheduler timeline (public npm trial @bryntum/scheduler-trial), read-only.
 * Loaded only behind ESCALES_BRYNTUM_ENABLED. Falls back to the local list if the package is absent.
 */
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

export default function BryntumTimeline({ events, onSelect, fallback }) {
  const { t } = useTranslation();
  const [Scheduler, setScheduler] = useState(null);
  const [failed, setFailed] = useState(false);
  const containerRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([import("@bryntum/scheduler"), import("@bryntum/scheduler/scheduler.css"), import("@bryntum/scheduler/stockholm-light.css")])
      .then(([mod]) => {
        if (!cancelled) setScheduler(() => mod.Scheduler || mod.default?.Scheduler);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!Scheduler || !containerRef.current || !events.length) return undefined;
    const instance = new Scheduler({
      appendTo: containerRef.current,
      readOnly: true,
      height: 220,
      startDate: events[0].startDate,
      endDate: events[events.length - 1].endDate,
      viewPreset: "weekAndMonth",
      columns: [{ text: t("scheduler.heading"), field: "name", width: 160 }],
      resources: [{ id: "route", name: "BI Escales" }],
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
          onSelect?.({ id: eventRecord.id, name: eventRecord.name, milestoneId: eventRecord.milestoneId });
        },
      },
    });
    return () => instance.destroy();
  }, [Scheduler, events, onSelect, t]);

  if (failed || !events.length) return fallback;
  if (!Scheduler) {
    return <p className="escales-scheduler-loading" data-testid="bryntum-loading">{t("scheduler.loading", "…")}</p>;
  }
  return <div className="escales-scheduler-bryntum" data-testid="escales-scheduler-bryntum" ref={containerRef} />;
}

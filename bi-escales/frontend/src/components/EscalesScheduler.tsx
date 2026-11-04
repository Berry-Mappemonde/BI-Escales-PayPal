import { useEffect, useState } from "react";
import { fetchFeatures, fetchSchedule } from "../api/escales";
import type { ScheduleEscale } from "../api/types";

const LOCAL_PREVIEW: ScheduleEscale[] = [
  { milestone_id: "dep-mayotte", name: "Mayotte", arrival_iso: "2026-09-01T08:00:00Z" },
  { milestone_id: "dep-fort-de-france", name: "Fort-de-France", arrival_iso: "2026-08-15T08:00:00Z" },
];

function rowsFromSchedule(body: Awaited<ReturnType<typeof fetchSchedule>>): ScheduleEscale[] {
  const fromExport = body.export?.escales;
  if (fromExport && fromExport.length > 0) return fromExport;
  if (body.milestones && body.milestones.length > 0) return body.milestones;
  return [];
}

export function EscalesScheduler() {
  const [rows, setRows] = useState<ScheduleEscale[]>(LOCAL_PREVIEW);
  const [source, setSource] = useState("local-preview");
  const [mode, setMode] = useState("local");

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const body = await fetchSchedule();
        const next = rowsFromSchedule(body);
        if (!cancelled && next.length > 0) {
          setRows(next);
          setSource(body.source || "api");
        }
      } catch {
        /* keep the local preview; it is display-only and is not written back */
      }
      try {
        const features = await fetchFeatures();
        if (cancelled || !features.bryntum) return;
        const specifier = "@bryntum/scheduler";
        await import(/* @vite-ignore */ specifier);
        if (!cancelled) setMode("bryntum");
      } catch {
        if (!cancelled) setMode("local");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <section className="panel escales-scheduler" data-testid="escales-scheduler" data-source={source}>
      <h2>Stopover calendar</h2>
      <p className="hint">Mode {mode}. Bryntum loads only when the API flag is on.</p>
      <ul className="escales-scheduler-list">
        {rows.map((row) => {
          const id = row.milestone_id || row.name || "escale";
          const when = (row.arrival_iso || "").slice(0, 10);
          return (
            <li key={id}>
              <strong>{row.name || row.title || id}</strong>
              {when ? <span> {when}</span> : null}
              <code> {id}</code>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

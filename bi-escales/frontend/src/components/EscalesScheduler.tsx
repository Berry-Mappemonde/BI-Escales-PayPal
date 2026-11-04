import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { fetchFeatures, fetchSchedule, listMilestones } from "../api/escales";
import type { Milestone, ScheduleEscale } from "../api/types";

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
  const { t } = useTranslation();
  const [rows, setRows] = useState<ScheduleEscale[]>(LOCAL_PREVIEW);
  const [ledgerById, setLedgerById] = useState<Record<string, string>>({});
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
        const milestones: Milestone[] = await listMilestones();
        if (!cancelled) {
          const map: Record<string, string> = {};
          for (const milestone of milestones) {
            const arrival = milestone.meta?.arrival_iso;
            if (arrival) map[milestone.id] = arrival;
          }
          setLedgerById(map);
          setRows((current) => {
            const known = new Set(current.map((row) => row.milestone_id || row.name));
            const extra = milestones
              .filter((milestone) => !known.has(milestone.id))
              .map((milestone) => ({
                milestone_id: milestone.id,
                name: milestone.meta?.title || milestone.id,
                arrival_iso: milestone.meta?.arrival_iso,
              }));
            return extra.length > 0 ? [...current, ...extra] : current;
          });
        }
      } catch {
        /* milestones stay empty until the API is up */
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
      <h2>{t("scheduler.heading")}</h2>
      <p className="hint">{t("scheduler.mode", { mode })}</p>
      <ul className="escales-scheduler-list">
        {rows.map((row) => {
          const id = row.milestone_id || row.name || "escale";
          const when = (row.arrival_iso || "").slice(0, 10);
          const ledger = (ledgerById[id] || "").slice(0, 10);
          const past = Boolean(row.arrival_iso) && Date.parse(row.arrival_iso || "") < Date.now();
          const mismatch = Boolean(ledger) && ledger !== when;
          return (
            <li key={id}>
              <strong>{row.name || row.title || id}</strong>
              {when ? (
                <span className={past ? "past-date" : undefined} data-testid={past ? "scheduler-past" : undefined}>
                  {" "}
                  {when}
                  {past ? ` (${t("scheduler.past")})` : ""}
                </span>
              ) : null}
              {mismatch ? (
                <span className="date-mismatch" data-testid="date-mismatch">
                  {" "}
                  {t("scheduler.ledgerDate", { date: ledger })}
                </span>
              ) : null}
              <code> {id}</code>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

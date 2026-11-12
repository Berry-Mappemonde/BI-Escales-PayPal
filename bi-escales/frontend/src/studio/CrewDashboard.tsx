import { useEffect, useMemo, useState } from "react";
import type { ColDef } from "ag-grid-community";
import { fetchPayPalSubscriptions } from "../api/escales";
import { crewMembershipRows } from "../components/TreasurerCrewMemberships";
import { DashboardGrid } from "./DashboardGrid";
import { dashboardCopy } from "./dashboardLocale";
import { studioT } from "./locale";

function membershipRows(items: unknown) {
  return crewMembershipRows(items).map((row) => ({
    id: row.subscription_id,
    email: String(row.subscriber_email ?? "").trim(),
    status: String(row.status ?? "").trim().toUpperCase(),
    updated: Date.parse(row.updated_at || row.at || ""),
  }));
}

type Membership = ReturnType<typeof membershipRows>[number];
type Result = { rows: Membership[] } | { error: true };

function statusLabel(value: string, language: string) {
  return value
    ? studioT(language)(`treasurer.paypal.crew.statuses.${value}`, { defaultValue: value })
    : dashboardCopy(language).unknown;
}

export function CrewDashboard({ adminKey, language, demo }: {
  adminKey: string;
  language: string;
  demo: boolean;
}) {
  const [result, setResult] = useState<Result>();
  const [request, setRequest] = useState(0);
  const [status, setStatus] = useState("");
  const copy = dashboardCopy(language);
  useEffect(() => {
    if (demo) return;
    let cancelled = false;
    void fetchPayPalSubscriptions(adminKey).then(
      ({ items }) => { if (!cancelled) setResult({ rows: membershipRows(items) }); },
      () => { if (!cancelled) setResult({ error: true }); },
    );
    return () => { cancelled = true; };
  }, [adminKey, demo, request]);

  const columns: ColDef<Membership>[] = useMemo(() => [
    { field: "email", headerName: copy.member, minWidth: 230, flex: 1.6 },
    { field: "status", headerName: copy.status, flex: 1, minWidth: 145,
      valueFormatter: ({ value }) => statusLabel(value, language) },
    { field: "updated", headerName: copy.updated, flex: 1, minWidth: 160,
      valueFormatter: ({ value }) => Number.isFinite(value)
        ? new Intl.DateTimeFormat(language, { dateStyle: "medium" }).format(value) : "—" },
    { field: "id", headerName: copy.subscription, flex: 1, minWidth: 170 },
  ], [copy, language]);

  if (demo) return <p className="studio-empty">{copy.crewDemo}</p>;
  if (!result) return <p className="studio-empty" role="status">{copy.crewLoading}</p>;
  if ("error" in result) return (
    <div className="studio-empty">
      <p role="alert">{copy.crewError}</p>
      <button type="button" onClick={() => { setResult(undefined); setRequest(request + 1); }}>{copy.refresh}</button>
    </div>
  );

  const rows = result.rows.filter((row) => !status || row.status === status);
  const statuses = [...new Set(result.rows.map((row) => row.status).filter(Boolean))].sort();
  return (
    <section className="studio-ledger" aria-label={copy.crew}>
      <div className="studio-controls">
        <label>{copy.status}
          <select value={status} onChange={(event) => setStatus(event.target.value)}>
            <option value="">{copy.allStatuses}</option>
            {statuses.map((option) => <option key={option} value={option}>{statusLabel(option, language)}</option>)}
          </select>
        </label>
      </div>
      <dl className="studio-totals" aria-live="polite">
        <div><dt>{copy.memberships}</dt><dd>{rows.length}</dd></div>
        <div><dt>{copy.active}</dt><dd>{rows.filter((row) => row.status === "ACTIVE").length}</dd></div>
      </dl>
      <DashboardGrid rows={rows} columns={columns} label={copy.crew} empty={copy.crewEmpty} />
    </section>
  );
}

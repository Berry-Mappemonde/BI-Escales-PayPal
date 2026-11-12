import { useMemo, useState, type ReactNode } from "react";
import type { ColDef } from "ag-grid-community";
import type { StopNames } from "../utils/milestoneLabel";
import {
  dashboardMoney, fundingTypes, groupLedger, ledgerTotals, totalFields,
  type GroupBy, type LedgerGroup, type LedgerPledge, type LedgerTotals,
} from "./dashboardLedger";
import { dashboardCopy, fundingLabel, ledgerStatus } from "./dashboardLocale";
import { DashboardGrid } from "./DashboardGrid";

function tone(status: string) {
  switch (status) {
    case "authorized": return "held";
    case "vaulted": return "saved";
    case "captured": return "captured";
    case "voided": return "released";
    case "refunded":
    case "partially_refunded": return "refunded";
    case "failed":
    case "charge_failed":
    case "capture_failed": return "error";
    default: return "pending";
  }
}

export function LedgerDashboard({
  rows, names, language, chart,
}: {
  rows: LedgerPledge[];
  names?: StopNames;
  language: string;
  chart?: (totals: LedgerTotals, currency: string) => ReactNode;
}) {
  const copy = dashboardCopy(language);
  const [type, setType] = useState("");
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [groupBy, setGroupBy] = useState<GroupBy | "">("target");
  const [selectedCurrency, setSelectedCurrency] = useState("");
  const currencies = useMemo(() => [...new Set(rows.map((row) => row.currency))].sort(), [rows]);
  const currency = currencies.includes(selectedCurrency) ? selectedCurrency
    : currencies.includes("EUR") ? "EUR" : currencies[0] ?? "EUR";
  const statuses = useMemo(() => [...new Set(rows.map((row) => row.status))]
    .sort((a, b) => ledgerStatus(a, language).localeCompare(ledgerStatus(b, language), language)), [rows, language]);

  const filtered = useMemo(() => {
    const query = search.trim().toLocaleLowerCase(language);
    return rows.filter((row) => row.currency === currency
      && (!type || row.type === type)
      && (!status || row.status === status)
      && (!query || fundingLabel(row, names, language).toLocaleLowerCase(language).includes(query)
        || row.target.toLocaleLowerCase(language).includes(query)));
  }, [rows, currency, search, type, status, names, language]);
  const totals = useMemo(() => ledgerTotals(filtered), [filtered]);
  const groups = useMemo(() => groupBy ? groupLedger(filtered, groupBy, (row) => {
    if (groupBy === "status") return ledgerStatus(row.status, language);
    if (groupBy === "type") return copy[row.type];
    return fundingLabel(row, names, language);
  }) : [], [filtered, groupBy, copy, names, language]);

  const groupColumns = useMemo<ColDef<LedgerGroup>[]>(() => [
    {
      field: "label", headerName: groupBy ? copy[groupBy] : copy.target, minWidth: 280, flex: 2.4, sort: "asc",
      cellRenderer: ({ data }: { data?: LedgerGroup }) => data && (
        <span className="studio-target">
          <strong title={data.label}>{data.label}</strong>{data.type && data.type !== "common" ? <small>{copy[data.type]}</small> : null}
        </span>
      ),
    },
    { field: "count", headerName: copy.count, maxWidth: 116, type: "rightAligned" },
    ...totalFields.map((field): ColDef<LedgerGroup> => ({
      field, headerName: copy[field], type: "rightAligned", flex: 1, minWidth: 124,
      valueFormatter: ({ value }) => dashboardMoney(value, currency, language),
    })),
  ], [groupBy, copy, currency, language]);

  const pledgeColumns = useMemo<ColDef<LedgerPledge>[]>(() => [
    { colId: "target", headerName: copy.target, flex: 1.5, minWidth: 200, sort: "asc",
      valueGetter: ({ data }) => data && fundingLabel(data, names, language) },
    { colId: "type", headerName: copy.type, flex: 1, minWidth: 130,
      valueGetter: ({ data }) => data && copy[data.type] },
    { colId: "status", headerName: copy.status, flex: 1, minWidth: 166,
      valueGetter: ({ data }) => data && ledgerStatus(data.status, language),
      cellRenderer: ({ data, value }: { data?: LedgerPledge; value?: string }) => (
        <span className="studio-status" data-tone={data && tone(data.status)}>{value}</span>
      ) },
    ...(["pledged", "captured", "refunded"] as const).map((field): ColDef<LedgerPledge> => ({
      field, headerName: copy[field], type: "rightAligned", flex: 1, minWidth: 125,
      valueFormatter: ({ value }) => dashboardMoney(value, currency, language),
    })),
  ], [copy, currency, language, names]);

  return (
    <section aria-label={copy.ledger} className="studio-ledger">
      <div className="studio-controls">
        <label className="studio-search">{copy.search}
          <input type="search" value={search} onChange={(event) => setSearch(event.target.value)}
            placeholder={copy.searchPlaceholder} />
        </label>
        <label>{copy.type}
          <select value={type} onChange={(event) => setType(event.target.value)}>
            <option value="">{copy.allTypes}</option>
            {fundingTypes.map((option) => <option key={option} value={option}>{copy[option]}</option>)}
          </select>
        </label>
        <label>{copy.status}
          <select value={status} onChange={(event) => setStatus(event.target.value)}>
            <option value="">{copy.allStatuses}</option>
            {statuses.map((option) => <option key={option} value={option}>{ledgerStatus(option, language)}</option>)}
          </select>
        </label>
        <label>{copy.groupBy}
          <select value={groupBy} onChange={(event) => setGroupBy(event.target.value as GroupBy | "")}>
            <option value="target">{copy.target}</option>
            <option value="type">{copy.type}</option>
            <option value="status">{copy.status}</option>
            <option value="">{copy.ungrouped}</option>
          </select>
        </label>
        {currencies.length > 1 && (
          <label>{copy.currency}
            <select value={currency} onChange={(event) => setSelectedCurrency(event.target.value)}>
              {currencies.map((option) => <option key={option}>{option}</option>)}
            </select>
          </label>
        )}
        <button type="button" className="studio-clear" disabled={!search && !type && !status}
          onClick={() => { setSearch(""); setType(""); setStatus(""); }}>{copy.clear}</button>
      </div>

      <dl className="studio-totals" aria-live="polite">
        {totalFields.map((field) => (
          <div key={field} data-total={field}>
            <dt>{copy[field]}</dt>
            <dd>{dashboardMoney(totals[field], currency, language)}</dd>
          </div>
        ))}
      </dl>

      {totals.captured === null || totals.refunded === null ? (
        <p className="studio-hint" role="status">{copy.refundUnknown}</p>
      ) : null}

      {chart?.(totals, currency)}

      <div className="studio-table-heading">
        <h3>{groupBy === "target" ? copy.fundingTitle : copy.ledger}</h3>
        <span className="studio-hint" role="status">
          {new Intl.NumberFormat(language).format(totals.count)} {copy.count.toLocaleLowerCase(language)} · {currency}
        </span>
      </div>
      {groupBy
        ? <DashboardGrid key={groupBy} rows={groups} columns={groupColumns} label={copy.ledger} empty={copy.noRows} />
        : <DashboardGrid rows={filtered} columns={pledgeColumns} label={copy.ledger} empty={copy.noRows} />}
    </section>
  );
}

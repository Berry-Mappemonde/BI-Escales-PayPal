// Optional ag-grid-community table. Excluded from the core tsc/vite graph.
// This is not AG Studio and not the Studio Agent Framework.
import { useMemo } from "react";
import { AgGridReact } from "ag-grid-react";
import type { ColDef } from "ag-grid-community";
import "ag-grid-community/styles/ag-grid.css";
import "ag-grid-community/styles/ag-theme-quartz.css";
import type { PledgeGaugeRow } from "../api/types";
import { gaugePercent } from "../utils/gauges";

export interface AgProps {
  rows: PledgeGaugeRow[];
}

export default function TreasurerGridAg({ rows }: AgProps) {
  const columnDefs = useMemo<ColDef<PledgeGaugeRow>[]>(
    () => [
      { field: "milestone_id", headerName: "Milestone", flex: 1 },
      {
        headerName: "Authorized",
        valueGetter: (p) =>
          p.data
            ? `${p.data.authorized_count} (${p.data.authorized_total_eur.toFixed(2)} €) · ${gaugePercent(p.data, "authorized")}%`
            : "",
        flex: 1,
      },
      {
        headerName: "Captured",
        valueGetter: (p) =>
          p.data
            ? `${p.data.captured_count} (${p.data.captured_total_eur.toFixed(2)} €) · ${gaugePercent(p.data, "captured")}%`
            : "",
        flex: 1,
      },
      {
        headerName: "Voided",
        valueGetter: (p) =>
          p.data ? `${p.data.voided_count} · ${gaugePercent(p.data, "voided")}%` : "",
        flex: 1,
      },
    ],
    [],
  );

  return (
    <div className="ag-theme-quartz" style={{ height: 280, width: "100%" }} data-testid="treasurer-ag-grid">
      <AgGridReact rowData={rows} columnDefs={columnDefs} domLayout="autoHeight" />
    </div>
  );
}

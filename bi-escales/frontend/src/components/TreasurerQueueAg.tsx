// Optional ag-grid-community treasurer queue (not AG Studio).
// Source: NAVIGUIDE/BI optional table pattern; wired from TreasurerQueue.tsx on PR #18.
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { AgGridReact } from "ag-grid-react";
import type { ColDef, ICellRendererParams } from "ag-grid-community";
import "ag-grid-community/styles/ag-grid.css";
import "ag-grid-community/styles/ag-theme-quartz.css";
import type { PublicPledge } from "../api/types";

export type QueueRow = PublicPledge & { verdict: string };

export interface TreasurerQueueAgProps {
  rows: QueueRow[];
  busyId: string | null;
  approveLabel: string;
  onApprove: (pledgeId: string, action: "capture" | "void") => void;
}

function ApproveCell({
  data,
  busyId,
  approveLabel,
  onApprove,
}: {
  data?: QueueRow;
  busyId: string | null;
  approveLabel: string;
  onApprove: TreasurerQueueAgProps["onApprove"];
}) {
  if (!data) return null;
  const proposal = data.verdict;
  const enabled = ["capture", "void"].includes(proposal) && busyId !== data.id;
  return (
    <button
      type="button"
      data-testid={`approve-${data.id}`}
      disabled={!enabled}
      onClick={() => onApprove(data.id, proposal as "capture" | "void")}
    >
      {approveLabel}
    </button>
  );
}

export default function TreasurerQueueAg({ rows, busyId, approveLabel, onApprove }: TreasurerQueueAgProps) {
  const { t } = useTranslation();
  const columnDefs = useMemo<ColDef<QueueRow>[]>(
    () => [
      { field: "status", headerName: t("treasurer.status"), filter: true, sortable: true, flex: 1 },
      {
        headerName: t("treasurer.amount"),
        filter: true,
        sortable: true,
        flex: 1,
        valueGetter: (p) => (p.data ? `${p.data.amount_eur} ${p.data.currency}` : ""),
      },
      { field: "description", headerName: t("treasurer.description"), filter: true, sortable: true, flex: 1.2 },
      { field: "milestone_id", headerName: t("treasurer.milestone"), filter: true, sortable: true, flex: 1 },
      {
        field: "verdict",
        headerName: t("treasurer.verdict"),
        filter: true,
        sortable: true,
        flex: 1,
        cellRenderer: (params: ICellRendererParams<QueueRow>) => (
          <span data-testid={`verdict-${params.data?.id}`}>{params.value || ""}</span>
        ),
      },
      {
        headerName: t("treasurer.actions"),
        sortable: false,
        filter: false,
        flex: 1,
        cellRenderer: (params: ICellRendererParams<QueueRow>) => (
          <ApproveCell
            data={params.data}
            busyId={busyId}
            approveLabel={approveLabel}
            onApprove={onApprove}
          />
        ),
      },
    ],
    [approveLabel, busyId, onApprove, t],
  );

  return (
    <div
      className="ag-theme-quartz treasurer-queue-grid"
      style={{ width: "100%", minHeight: 120 }}
      data-testid="treasurer-queue-ag-grid"
    >
      <AgGridReact rowData={rows} columnDefs={columnDefs} domLayout="autoHeight" />
    </div>
  );
}

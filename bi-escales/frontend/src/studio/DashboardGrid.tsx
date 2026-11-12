import {
  CellStyleModule,
  ClientSideRowModelModule,
  RenderApiModule,
  themeQuartz,
  type ColDef,
  type GetRowIdParams,
} from "ag-grid-community";
import { AgGridReact } from "ag-grid-react";

const modules = [CellStyleModule, ClientSideRowModelModule, RenderApiModule];
const theme = themeQuartz.withParams({
  fontFamily: "var(--font-sans)",
  fontSize: 13,
  backgroundColor: "var(--color-panel)",
  foregroundColor: "var(--color-fg)",
  accentColor: "var(--color-accent)",
  headerBackgroundColor: "var(--color-raised)",
  headerTextColor: "var(--color-fg-2)",
  borderColor: "var(--color-line)",
  rowHoverColor: "var(--color-raised)",
  wrapperBorderRadius: "var(--radius-panel)",
  rowHeight: 46,
  headerHeight: 42,
  browserColorScheme: "inherit",
});
const columnDefaults: ColDef = { resizable: true, sortable: true, minWidth: 112 };

function rowId<Row extends { id: string }>({ data }: GetRowIdParams<Row>) {
  return data.id;
}

export function DashboardGrid<Row extends { id: string }>({
  rows,
  columns,
  label,
  empty,
}: {
  rows: Row[];
  columns: ColDef<Row>[];
  label: string;
  empty: string;
}) {
  if (rows.length === 0) return <p className="studio-empty" role="status">{empty}</p>;

  return (
    <div className="studio-grid" style={{ height: Math.min(480, 44 + rows.length * 46) }}>
      <AgGridReact<Row>
        onGridReady={({ api }) => api.setGridAriaProperty("label", label)}
        theme={theme}
        modules={modules}
        rowData={rows}
        columnDefs={columns}
        defaultColDef={columnDefaults}
        getRowId={rowId}
        suppressMovableColumns
        suppressColumnVirtualisation
        animateRows={false}
      />
    </div>
  );
}

import { useEffect } from "react";
import type { AgWidgetParams } from "ag-studio";
import { dashboardMoney, totalFields, type LedgerGroup } from "./dashboardLedger";
import { dashboardCopy } from "./dashboardLocale";

export interface ReportContext {
  groups: LedgerGroup[];
  currency: string;
  language: string;
}

export function FundingWidget({ context, widgetApi }: AgWidgetParams) {
  const { groups, currency, language } = context as ReportContext;
  const copy = dashboardCopy(language);
  useEffect(() => {
    widgetApi.setDisplayState(groups.length ? "displayed" : "noData");
  }, [groups, widgetApi]);

  return (
    <div className="studio-widget-scroll">
      <table className="studio-funding-widget">
        <thead><tr>
          <th scope="col">{copy.target}</th>
          {totalFields.map((field) => <th key={field} scope="col">{copy[field]}</th>)}
        </tr></thead>
        <tbody>{groups.map((group) => (
          <tr key={group.id}>
            <th scope="row">{group.label}</th>
            {totalFields.map((field) => (
              <td key={field}>{dashboardMoney(group[field], currency, language)}</td>
            ))}
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}

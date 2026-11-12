import { useMemo, useState } from "react";
import { AgStudio, AgStudioProvider } from "ag-studio-react";
import { agStudioLlmEndpoint } from "../config/features";
import { agStudioLocaleText } from "./agStudioLocale";
import { escalesStudioTheme } from "./escalesTheme";
import { treasurerInitialState } from "./initialReport";
import { pledgeStudioData } from "./pledgeData";
import { AgStudioAiModule, createTreasurerHarness } from "./treasurerAgent";
import { escalesWidgets } from "./widgets";
import { groupLedger, ledgerTotals, type LedgerPledge } from "./dashboardLedger";
import { dashboardCopy, fundingLabel } from "./dashboardLocale";
import type { StopNames } from "../utils/milestoneLabel";
import type { ReportContext } from "./FundingWidget";

const agentModules = [AgStudioAiModule];

export default function StudioReport({ rows, stopNames, language, licenseKey, agent }: {
  rows: LedgerPledge[];
  stopNames?: StopNames;
  language: string;
  licenseKey: string;
  agent: boolean;
}) {
  const [selectedCurrency, setSelectedCurrency] = useState("");
  const currencies = useMemo(() => [...new Set(rows.map((row) => row.currency))].sort(), [rows]);
  const currency = selectedCurrency || (currencies.includes("EUR") ? "EUR" : currencies[0] ?? "EUR");
  const scoped = useMemo(() => rows.filter((row) => row.currency === currency), [rows, currency]);
  const totals = useMemo(() => ledgerTotals(scoped), [scoped]);
  const data = useMemo(() => pledgeStudioData(scoped, language, currency, (row) =>
    fundingLabel(row, stopNames, language)), [scoped, language, currency, stopNames]);
  const context = useMemo<ReportContext>(() => ({
    groups: groupLedger(scoped, "target", (row) => fundingLabel(row, stopNames, language)),
    currency,
    language,
  }), [scoped, stopNames, currency, language]);
  const initialState = useMemo(() => treasurerInitialState(language, totals.captured !== null), [language, totals.captured]);
  const widgets = useMemo(() => (config: Parameters<typeof escalesWidgets>[0]) => escalesWidgets(config, language), [language]);
  const localeText = useMemo(() => agStudioLocaleText(language), [language]);
  const ai = useMemo(() => agent
    ? createTreasurerHarness(agStudioLlmEndpoint(), language, { currency, totals })
    : undefined, [agent, language, currency, totals]);
  const copy = dashboardCopy(language);
  const mode = document.documentElement.dataset.theme === "light" ? "light" : "dark";

  return (
    <>
      {currencies.length > 1 && (
        <div className="studio-controls">
          <label>{copy.currency}
            <select value={currency} onChange={(event) => setSelectedCurrency(event.target.value)}>
              {currencies.map((option) => <option key={option}>{option}</option>)}
            </select>
          </label>
        </div>
      )}
      {totals.captured === null || totals.refunded === null ? <p className="studio-hint">{copy.refundUnknown}</p> : null}
      <div className="ag-theme-mode treasurer-studio" data-ag-theme-mode={mode}>
        <AgStudioProvider licenseKey={licenseKey} modules={agent ? agentModules : undefined}>
          <AgStudio key={`${language}:${currency}`} style={{ height: "100%", width: "100%" }}
            theme={escalesStudioTheme}
            data={data}
            context={context}
            initialState={initialState}
            widgets={widgets}
            ai={ai}
            localeText={localeText}
            mode={agent ? "edit" : "view"}
          />
        </AgStudioProvider>
      </div>
    </>
  );
}

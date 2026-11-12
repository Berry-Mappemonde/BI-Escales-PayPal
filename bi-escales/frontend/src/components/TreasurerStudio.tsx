import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import { listPledges } from "../api/escales";
import { agGridLicenseKey } from "../config/features";
import { CrewDashboard } from "../studio/CrewDashboard";
import { LedgerDashboard } from "../studio/LedgerDashboard";
import { dashboardCopy } from "../studio/dashboardLocale";
import { ledgerPledges, type LedgerPledge } from "../studio/dashboardLedger";
import type { dashboardCapabilities } from "../studio/dashboardLicense";
import type { StopNames } from "../utils/milestoneLabel";
import "../studio/studio.css";

const LedgerChart = lazy(() => import("../studio/LedgerChart"));
const StudioReport = lazy(() => import("../studio/StudioReport"));

type LedgerResult = { rows: LedgerPledge[] } | { error: true };
type View = "ledger" | "crew" | "report";

export default function TreasurerStudio({ adminKey, demo, stopNames, onClose }: {
  adminKey: string;
  demo: boolean;
  stopNames?: StopNames;
  onClose: () => void;
}) {
  const { i18n } = useTranslation();
  const language = i18n.resolvedLanguage ?? i18n.language;
  const copy = dashboardCopy(language);
  const [result, setResult] = useState<LedgerResult>();
  const [request, setRequest] = useState(0);
  const [view, setView] = useState<View>("ledger");
  const [showChart, setShowChart] = useState(false);
  const [capabilities, setCapabilities] = useState<ReturnType<typeof dashboardCapabilities>>();
  const dialog = useRef<HTMLDialogElement>(null);
  const licenseKey = agGridLicenseKey();

  useEffect(() => {
    const element = dialog.current;
    element?.showModal();
    return () => element?.close();
  }, []);

  useEffect(() => {
    let cancelled = false;
    void listPledges(demo ? "" : adminKey, demo ? { demoTreasurer: true } : undefined)
      .then(ledgerPledges)
      .then(
        (rows) => { if (!cancelled) setResult({ rows }); },
        () => { if (!cancelled) setResult({ error: true }); },
      );
    return () => { cancelled = true; };
  }, [adminKey, demo, request]);

  useEffect(() => {
    if (!licenseKey) return;
    let cancelled = false;
    void import("../studio/dashboardLicense").then(
      ({ dashboardCapabilities }) => { if (!cancelled) setCapabilities(dashboardCapabilities(licenseKey)); },
      () => { /* The ledger remains available if optional commercial modules fail to load. */ },
    );
    return () => { cancelled = true; };
  }, [licenseKey]);

  const close = () => {
    dialog.current?.close();
    onClose();
  };
  const refresh = () => {
    setResult(undefined);
    setRequest((value) => value + 1);
  };
  const rows = result && "rows" in result ? result.rows : null;
  const status = <p className="studio-empty" role="status">{copy.loading}</p>;

  return createPortal(
    <dialog ref={dialog} className="studio-overlay" aria-labelledby="studio-dashboard-heading"
      onKeyDown={(event) => { if (event.key === "Escape") event.stopPropagation(); }}
      onCancel={(event) => { event.preventDefault(); close(); }}>
      <div className="studio-workspace" data-testid="treasurer-ag-studio">
        <header className="studio-overlay-header">
          <div>
            <h2 id="studio-dashboard-heading">{copy.title}</h2>
            <p>{copy.readOnly}{demo && <span className="studio-demo">{copy.demo}</span>}</p>
          </div>
          <div className="studio-actions">
            <button type="button" className="secondary" onClick={refresh} disabled={!result}>{copy.refresh}</button>
            <button type="button" className="secondary" data-testid="treasurer-studio-close" onClick={close}>
              {copy.close}
            </button>
          </div>
        </header>

        {rows ? (
          <>
            <nav className="studio-nav" aria-label={copy.title}>
              <button type="button" aria-pressed={view === "ledger"} onClick={() => setView("ledger")}>{copy.ledger}</button>
              {!demo && adminKey.trim() && <button type="button" aria-pressed={view === "crew"} onClick={() => setView("crew")}>{copy.crew}</button>}
              {capabilities?.studio && (
                <button type="button" aria-pressed={view === "report"} onClick={() => setView("report")}>
                  {capabilities.agent && !demo ? copy.agent : copy.report}
                </button>
              )}
              {capabilities?.charts && view === "ledger" && (
                <button type="button" className="studio-chart-toggle" aria-pressed={showChart}
                  onClick={() => setShowChart(!showChart)}>{copy.charts}</button>
              )}
            </nav>
            <div hidden={view !== "ledger"}>
              <LedgerDashboard rows={rows} names={stopNames} language={language}
                chart={view === "ledger" && showChart && capabilities?.charts && licenseKey
                  ? (totals, currency) => <Suspense fallback={status}>
                    <LedgerChart totals={totals} currency={currency} language={language} licenseKey={licenseKey} />
                  </Suspense> : undefined} />
            </div>
            {view === "crew" && !demo && adminKey.trim() && <CrewDashboard adminKey={adminKey} language={language} demo={demo} />}
            {view === "report" && capabilities?.studio && licenseKey && (
              <Suspense fallback={status}>
                <StudioReport rows={rows} stopNames={stopNames} language={language} licenseKey={licenseKey}
                  agent={capabilities.agent && !demo} />
              </Suspense>
            )}
          </>
        ) : result ? <p className="studio-empty" role="alert">{copy.loadError}</p> : status}
      </div>
    </dialog>,
    document.body,
  );
}

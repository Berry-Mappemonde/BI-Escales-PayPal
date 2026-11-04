import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { fetchHealth, listMilestones } from "./api/escales";
import type { Milestone, PublicPledge } from "./api/types";
import { DemoModeBanner } from "./components/DemoModeBanner";
import { EscalesPanel } from "./components/EscalesPanel";
import { EscalesScheduler } from "./components/EscalesScheduler";
import { FinanceLedgerPanel } from "./components/FinanceLedgerPanel";
import { PledgeLifecycle } from "./components/PledgeLifecycle";
import { TreasurerGrid } from "./components/TreasurerGrid";
import { TreasurerQueue } from "./components/TreasurerQueue";
import { setLanguage } from "./i18n";
import { usePledgeQueue } from "./hooks/usePledgeQueue";
import "./styles/app.css";

export default function App() {
  const { t, i18n } = useTranslation();
  const [healthOk, setHealthOk] = useState<boolean | null>(null);
  const [escalesOk, setEscalesOk] = useState<boolean | null>(null);
  const [milestones, setMilestones] = useState<Milestone[]>([]);
  const [selectedMilestone, setSelectedMilestone] = useState("dep-mayotte");
  const [adminKey, setAdminKey] = useState("");
  const { pledges, loading, error, needsKey, refresh, updatePledge } = usePledgeQueue(adminKey);

  useEffect(() => {
    void fetchHealth()
      .then(() => setHealthOk(true))
      .catch(() => setHealthOk(false));
    void listMilestones()
      .then((m) => {
        setEscalesOk(true);
        setMilestones(m);
      })
      .catch(() => setEscalesOk(false));
  }, []);

  const onAuthorized = useCallback(
    (pledge: PublicPledge) => {
      updatePledge(pledge);
      void refresh();
    },
    [refresh, updatePledge],
  );

  return (
    <div className="app-shell">
      <header className="app-header">
        <div>
          <h1>{t("app.title")}</h1>
          <p>{t("app.tagline")}</p>
        </div>
        <div className="lang-switch">
          <button
            type="button"
            className={i18n.language === "fr" ? "active" : ""}
            onClick={() => setLanguage("fr")}
          >
            {t("app.langFr")}
          </button>
          <button
            type="button"
            className={i18n.language === "en" ? "active" : ""}
            onClick={() => setLanguage("en")}
          >
            {t("app.langEn")}
          </button>
        </div>
      </header>

      <DemoModeBanner />

      <p
        className={`health ${healthOk === false ? "bad" : "ok"}`}
        data-testid="health-status"
        role="status"
      >
        {healthOk === null ? t("app.healthLoading") : healthOk ? t("app.healthOk") : t("app.healthFail")}
      </p>
      {escalesOk === false ? <p className="notice warn">{t("app.escalesOff")}</p> : null}

      <EscalesScheduler />

      <main className="layout">
        <EscalesPanel
          onPledgeAuthorized={(p) => {
            onAuthorized(p);
            setSelectedMilestone(p.milestone_id);
          }}
        />
        <div className="treasurer-column">
          <label className="admin-key shared-admin">
            {t("treasurer.adminKey")}
            <input
              type="password"
              autoComplete="off"
              value={adminKey}
              onChange={(e) => setAdminKey(e.target.value)}
              data-testid="admin-key-input"
            />
          </label>
          <TreasurerQueue
            pledges={pledges}
            loading={loading}
            error={error}
            needsKey={needsKey}
            adminKey={adminKey}
            onRefresh={() => void refresh()}
            onUpdated={updatePledge}
          />
          <PledgeLifecycle pledges={pledges} needsKey={needsKey} />
          <TreasurerGrid
            pledges={pledges}
            milestones={milestones}
            adminKey={adminKey}
            selectedMilestoneId={selectedMilestone}
            onSelectMilestone={setSelectedMilestone}
            onMilestonesChange={setMilestones}
            onPledgeUpdated={updatePledge}
          />
          <FinanceLedgerPanel adminKey={adminKey} />
        </div>
      </main>
    </div>
  );
}

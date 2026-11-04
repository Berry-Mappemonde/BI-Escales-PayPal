import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { fetchHealth, listMilestones } from "./api/escales";
import type { Milestone, PublicPledge } from "./api/types";
import { EscalesPanel } from "./components/EscalesPanel";
import { TreasurerGrid, TreasurerStudioSection } from "./components/TreasurerGrid";
import { TreasurerQueue } from "./components/TreasurerQueue";
import { setLanguage } from "./i18n";
import { usePledgeQueue } from "./hooks/usePledgeQueue";
import "./styles/app.css";

export default function App() {
  const { t, i18n } = useTranslation();
  const { pledges, loading, refresh, register, updatePledge } = usePledgeQueue();
  const [healthOk, setHealthOk] = useState<boolean | null>(null);
  const [escalesOk, setEscalesOk] = useState<boolean | null>(null);
  const [milestones, setMilestones] = useState<Milestone[]>([]);
  const [selectedMilestone, setSelectedMilestone] = useState("dep-mayotte");
  const [adminKey, setAdminKey] = useState("");

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
      register(pledge.id);
      updatePledge(pledge);
    },
    [register, updatePledge],
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

      <p className={`health ${healthOk ? "ok" : "bad"}`}>
        {healthOk ? t("app.healthOk") : t("app.healthFail")}
      </p>
      {escalesOk === false ? <p className="notice warn">{t("app.escalesOff")}</p> : null}

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
            adminKey={adminKey}
            onRefresh={() => void refresh()}
            onUpdated={updatePledge}
          />
          <TreasurerGrid
            pledges={pledges}
            milestones={milestones}
            adminKey={adminKey}
            selectedMilestoneId={selectedMilestone}
            onSelectMilestone={setSelectedMilestone}
            onMilestonesChange={setMilestones}
            onPledgeUpdated={updatePledge}
          />
        </div>
      </main>
      <TreasurerStudioSection pledges={pledges} />
    </div>
  );
}

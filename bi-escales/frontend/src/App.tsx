import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { fetchFeatures, fetchFund, fetchHealth, fetchSchedule, listMilestones } from "./api/escales";
import type { CaptainChatResponse, FeatureFlags, FundView, Milestone, PublicPledge, ScheduleResponse } from "./api/types";
import { EscalesPanel } from "./components/EscalesPanel";
import EscalesScheduler from "./components/escales/EscalesScheduler.jsx";
import { EscalePopup } from "./components/EscalePopup.jsx";
import MarinasPanel from "./components/MarinasPanel.jsx";
import ProjectList from "./components/ProjectList.jsx";
import { TreasurerGrid } from "./components/TreasurerGrid";
import { TreasurerQueue } from "./components/TreasurerQueue";
import { HELLOASSO_MEMBERSHIP_URL } from "./config/helloasso.js";
import { usePledgeQueue } from "./hooks/usePledgeQueue";
import { setLanguage } from "./i18n";
import { MapScene } from "./map/MapScene.jsx";
import { ficheMarinas, loadEscaleFiche } from "./marinas/escaleFiche.js";
import { fetchJson, sampleAt, voyageFromRoute } from "./voyage/loadVoyage.js";
import { resolveDepartureT0 } from "./voyage/departureT0.js";
import { matchVoyageStop } from "./voyage/milestoneId.js";
import { formatCivilDate } from "./voyage/voyageClock.js";
import "./styles/app.css";

type TabId = "voyage" | "marinas";

type VoyageStop = {
  name: string;
  lat: number;
  lon: number;
  milestoneId: string;
  flags?: string[];
};

type FlyTarget = { lat: number; lon: number; ts: number };

export default function App() {
  const { t, i18n } = useTranslation();
  const [tab, setTab] = useState<TabId>("voyage");
  const [healthOk, setHealthOk] = useState<boolean | null>(null);
  const [escalesOk, setEscalesOk] = useState<boolean | null>(null);
  const [milestones, setMilestones] = useState<Milestone[]>([]);
  const [schedule, setSchedule] = useState<ScheduleResponse | null>(null);
  const [features, setFeatures] = useState<FeatureFlags>({ bryntum: false });
  const [adminKey, setAdminKey] = useState("");
  const { pledges, loading, error, needsKey, refresh, updatePledge } = usePledgeQueue(adminKey);

  const [routeFc, setRouteFc] = useState<unknown>(null);
  const [projects, setProjects] = useState<{ features?: unknown[] }>({ features: [] });
  const [devT0, setDevT0] = useState("");
  const [now, setNow] = useState(() => new Date());
  const [stop, setStop] = useState<VoyageStop | null>(null);
  const [fiche, setFiche] = useState<unknown>(null);
  const [ficheLoading, setFicheLoading] = useState(false);
  const [ficheError, setFicheError] = useState<string | null>(null);
  const [flyTo, setFlyTo] = useState<FlyTarget | null>(null);
  const [amount, setAmount] = useState("20.00");
  const [description, setDescription] = useState("");
  const [contributor, setContributor] = useState("");
  const [milestoneId, setMilestoneId] = useState("dep-mayotte");
  const [fund, setFund] = useState<FundView | null>(null);

  const prod = Boolean(import.meta.env.PROD);
  const t0 = resolveDepartureT0(prod, devT0 || undefined);
  const lang = i18n.language?.startsWith("en") ? "en" : "fr";
  const voyage = useMemo(
    () => (routeFc ? voyageFromRoute(routeFc, t0) : null),
    [routeFc, t0],
  );
  const sample = useMemo(
    () => (voyage ? sampleAt(voyage.clock, now) : null),
    [voyage, now],
  );

  useEffect(() => {
    void fetchHealth().then(() => setHealthOk(true)).catch(() => setHealthOk(false));
    void listMilestones()
      .then((rows) => {
        setEscalesOk(true);
        setMilestones(rows);
      })
      .catch(() => setEscalesOk(false));
    void fetchSchedule().then(setSchedule).catch(() => setSchedule(null));
    void fetchFeatures().then(setFeatures).catch(() => setFeatures({ bryntum: false }));
    void fetchJson("/route.geojson").then(setRouteFc).catch(() => setRouteFc(null));
    void fetchJson("/bi-projects.geojson").then(setProjects).catch(() => setProjects({ features: [] }));
  }, []);

  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 30000);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    if (!stop) {
      setFiche(null);
      return undefined;
    }
    let cancelled = false;
    setFicheLoading(true);
    setFicheError(null);
    void loadEscaleFiche(stop, lang)
      .then((doc) => {
        if (!cancelled) setFiche(doc);
      })
      .catch((err: unknown) => {
        if (!cancelled) setFicheError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setFicheLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [stop, lang]);

  useEffect(() => {
    if (!milestoneId) {
      setFund(null);
      return undefined;
    }
    let cancelled = false;
    void fetchFund(milestoneId)
      .then((row) => {
        if (!cancelled) setFund(row);
      })
      .catch(() => {
        if (!cancelled) setFund(null);
      });
    return () => {
      cancelled = true;
    };
  }, [milestoneId, pledges]);

  const chooseStop = (next: VoyageStop) => {
    setStop(next);
    setMilestoneId(next.milestoneId);
    setDescription((prev) => prev || next.name);
    if (Number.isFinite(next.lat) && Number.isFinite(next.lon)) {
      setFlyTo({ lat: next.lat, lon: next.lon, ts: Date.now() });
    }
  };

  const onAuthorized = useCallback((pledge: PublicPledge) => {
    updatePledge(pledge);
    void refresh();
  }, [refresh, updatePledge]);

  const onSuggested = (pledge: CaptainChatResponse["suggested_pledge"]) => {
    if (!pledge) return;
    setAmount(pledge.amount_eur);
    setDescription(pledge.description);
    setMilestoneId(pledge.milestone_id);
  };

  const marinaFeatures = ficheMarinas(fiche);
  const cumNm = Number(sample?.sailNm ?? sample?.cumNm ?? 0);
  const onFlyTo = (_id: string, lat: number, lon: number) => {
    setFlyTo({ lat, lon, ts: Date.now() });
  };

  return (
    <div className="app-shell">
      <header className="app-header">
        <div>
          <h1>{t("app.title")}</h1>
          <p>{t("app.tagline")}</p>
        </div>
        <div className="lang-switch">
          <button type="button" className={i18n.language === "fr" ? "active" : ""} onClick={() => setLanguage("fr")}>
            {t("app.langFr")}
          </button>
          <button type="button" className={i18n.language === "en" ? "active" : ""} onClick={() => setLanguage("en")}>
            {t("app.langEn")}
          </button>
        </div>
      </header>

      <div className="tab-bar" role="tablist">
        <button type="button" role="tab" aria-selected={tab === "voyage"} className={tab === "voyage" ? "active" : ""} onClick={() => setTab("voyage")}>
          {t("tabs.voyage")}
        </button>
        <button type="button" role="tab" aria-selected={tab === "marinas"} className={tab === "marinas" ? "active" : ""} onClick={() => setTab("marinas")}>
          {t("tabs.marinas")}
        </button>
      </div>

      <p className={`health ${healthOk ? "ok" : "bad"}`}>
        {healthOk ? t("app.healthOk") : t("app.healthFail")}
      </p>
      {escalesOk === false ? <p className="notice warn">{t("app.escalesOff")}</p> : null}

      <MapScene
        segments={voyage?.segments || []}
        stops={voyage?.stops || []}
        boat={sample && Number.isFinite(sample.lat) ? { lat: sample.lat, lon: sample.lon, bearing: sample.bearing } : null}
        projects={projects}
        marinas={marinaFeatures}
        showProjects={tab === "voyage"}
        showMarinas={tab === "marinas"}
        flyTo={flyTo}
        onSelectStop={chooseStop}
      />

      <p className="voyage-clock" data-testid="voyage-clock">
        {formatCivilDate(sample?.iso, lang)}
        {" · cumNm "}
        {Number.isFinite(cumNm) ? cumNm.toFixed(1) : "—"}
        {sample?.status === "waiting" && sample.countdownHours != null
          ? ` · ${t("clock.waiting", { hours: Math.round(Number(sample.countdownHours)) })}`
          : ""}
      </p>
      {!prod ? (
        <label className="dev-t0">
          {t("clock.devT0")}
          <input
            type="text"
            value={devT0 || t0}
            onChange={(event) => setDevT0(event.target.value)}
            aria-label={t("clock.devT0")}
          />
        </label>
      ) : null}

      {tab === "voyage" ? (
        <div className="layout">
          <div>
            <ProjectList projects={projects} onFlyTo={onFlyTo} />
            <EscalesScheduler
              schedule={schedule}
              features={features}
              onSelectEscale={(event: { milestoneId?: string; name?: string }) => {
                const match = matchVoyageStop(voyage?.stops || [], event);
                if (match) chooseStop(match);
                else if (event.milestoneId) setMilestoneId(event.milestoneId);
              }}
            />
            <EscalesPanel
              part="chat"
              milestoneId={milestoneId}
              onMilestoneId={setMilestoneId}
              onSuggested={onSuggested}
              onAuthorized={onAuthorized}
            />
          </div>
          <div>
            {stop ? (
              <EscalePopup
                stop={stop}
                fiche={fiche}
                loading={ficheLoading}
                error={ficheError}
                onClose={() => setStop(null)}
                pledge={{
                  amount,
                  description,
                  milestoneId,
                  contributor,
                  onAmount: setAmount,
                  onDescription: setDescription,
                  onMilestoneId: setMilestoneId,
                  onContributor: setContributor,
                }}
                onPledgeAuthorized={onAuthorized}
              />
            ) : <p className="hint">{t("sheet.pick")}</p>}
            <p className="fund-line" data-testid="common-fund">
              {fund ? (
                <span>
                  {t("fund.figures", {
                    balance: fund.balance_eur,
                    currency: fund.currency,
                    income: fund.income_eur,
                    spending: fund.spending_eur,
                  })}
                  {" · "}
                </span>
              ) : null}
              {t("fund.line")}{" "}
              <a href={HELLOASSO_MEMBERSHIP_URL} target="_blank" rel="noreferrer">{t("fund.helloasso")}</a>
            </p>
          </div>
        </div>
      ) : (
        <div className="layout">
          <div className="panel">
            <h2>{t("marinas.pick")}</h2>
            <ul className="stop-picks">
              {(voyage?.stops || []).map((item: VoyageStop, index: number) => (
                <li key={`${item.milestoneId}-${index}`}>
                  <button type="button" onClick={() => chooseStop(item)}>{item.name}</button>
                </li>
              ))}
            </ul>
          </div>
          <MarinasPanel
            marinas={marinaFeatures}
            onFlyTo={onFlyTo}
            milestoneId={milestoneId}
            contributor={contributor}
            onAuthorized={onAuthorized}
          />
        </div>
      )}

      <section className="treasurer-column">
        <h2>{t("treasurer.heading")}</h2>
        <label className="admin-key shared-admin">
          {t("treasurer.adminKey")}
          <input
            type="password"
            autoComplete="off"
            value={adminKey}
            onChange={(event) => setAdminKey(event.target.value)}
            data-testid="admin-key-input"
          />
        </label>
        <p className="hint">{t("treasurer.adminKeyHint")}</p>
        <EscalesPanel part="evidence" milestoneId={milestoneId} onMilestoneId={setMilestoneId} />
        <TreasurerQueue
          pledges={pledges}
          loading={loading}
          error={error}
          needsKey={needsKey}
          adminKey={adminKey}
          onRefresh={() => void refresh()}
          onUpdated={updatePledge}
        />
        <TreasurerGrid
          pledges={pledges}
          milestones={milestones}
          adminKey={adminKey}
          selectedMilestoneId={milestoneId}
          onSelectMilestone={setMilestoneId}
          onMilestonesChange={setMilestones}
          onPledgeUpdated={updatePledge}
        />
      </section>
    </div>
  );
}

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { authorizePledge, fetchFund, fetchFeatures, fetchHealthRetrying, readPaypalReturn, readVaultReturn, recordSpending, registerVault, settleClock } from "./api/escales";
import { emitPledgeReturn } from "./paypal/pledgeReturnEvents";
import { nextStopover } from "./voyage/nextStopover.js";
import type { CaptainChatResponse, FundView, PublicPledge } from "./api/types";
import { EscalesPanel } from "./components/EscalesPanel";
import { EscalePopup } from "./components/EscalePopup.jsx";
import MarinasPanel from "./components/MarinasPanel.jsx";
import ProjectList from "./components/ProjectList.jsx";
import { TreasurerPanel } from "./components/TreasurerPanel";
import { CrewSubscribeButton } from "./components/CrewSubscribeButton";
import { usePledgeQueue } from "./hooks/usePledgeQueue";
import { setLanguage } from "./i18n";
import { MapScene } from "./map/MapScene.jsx";
import { ficheMarinas, loadEscaleFiche } from "./marinas/escaleFiche.js";
import { fetchJson, sampleAt, voyageFromRoute } from "./voyage/loadVoyage.js";
import { resolveDepartureT0 } from "./voyage/departureT0.js";
import { formatCivilDate } from "./voyage/voyageClock.js";
import "./styles/app.css";
import "./styles/naviguide-shell.css";

type TabId = "voyage" | "marinas";

type VoyageStop = {
  name: string;
  lat: number;
  lon: number;
  milestoneId: string;
  flags?: string[];
};

type FlyTarget = { lat: number; lon: number; ts: number };

const KIND_AMOUNT: Record<string, string | null> = {
  mile: null,
  night: "60.00",
  meal: "60.00",
  care: "40.00",
  common_fund: null,
};

export default function App() {
  const { t, i18n } = useTranslation();
  const [tab, setTab] = useState<TabId>("voyage");
  const [healthOk, setHealthOk] = useState<boolean | null>(null);
  const [hash, setHash] = useState(() => window.location.hash);
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
  const [amount, setAmount] = useState("1.00");
  const [contributor, setContributor] = useState("");
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const prevTabRef = useRef<TabId>("voyage");
  const [kind, setKind] = useState("mile");
  const [milestoneId, setMilestoneId] = useState("");
  const [fund, setFund] = useState<FundView | null>(null);
  const [paypalNote, setPaypalNote] = useState<string | null>(null);
  const [spendAmount, setSpendAmount] = useState("10.00");
  const [spendNote, setSpendNote] = useState("");
  const [spendError, setSpendError] = useState<string | null>(null);
  const [settleBusy, setSettleBusy] = useState(false);
  const [settleNote, setSettleNote] = useState<string | null>(null);
  const [clockPinned, setClockPinned] = useState(false);
  const [settleAt, setSettleAt] = useState("");
  const [projectFund, setProjectFund] = useState<FundView | null | undefined>(undefined);
  const [boatFund, setBoatFund] = useState<FundView | null | undefined>(undefined);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [treasurerOpen, setTreasurerOpen] = useState(false);

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
  const cumNm = Number(sample?.sailNm ?? sample?.cumNm ?? 0);

  useEffect(() => {
    document.body.classList.add("ng-naviguide-shell");
    return () => document.body.classList.remove("ng-naviguide-shell");
  }, []);

  useEffect(() => {
    let cancelled = false;
    void fetchHealthRetrying()
      .then(() => {
        if (!cancelled) setHealthOk(true);
      })
      .catch(() => {
        if (!cancelled) setHealthOk((current) => (current === true ? true : false));
      });
    void fetchJson("/route.geojson").then(setRouteFc).catch(() => setRouteFc(null));
    void fetchJson("/bi-projects.geojson").then(setProjects).catch(() => setProjects({ features: [] }));
    return () => {
      cancelled = true;
    };
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
    if (hash === "#tresorier") setTreasurerOpen(true);
  }, [hash]);

  useEffect(() => {
    if (!treasurerOpen || !milestoneId) {
      if (!treasurerOpen) setFund(null);
      return undefined;
    }
    let cancelled = false;
    void fetchFund(milestoneId, adminKey)
      .then((row) => {
        if (!cancelled) setFund(row);
      })
      .catch(() => {
        if (!cancelled) setFund(null);
      });
    return () => {
      cancelled = true;
    };
  }, [milestoneId, pledges, treasurerOpen, adminKey]);

  const chooseStop = (next: VoyageStop) => {
    setStop(next);
    setMilestoneId(next.milestoneId);
    if (Number.isFinite(next.lat) && Number.isFinite(next.lon)) {
      setFlyTo({ lat: next.lat, lon: next.lon, ts: Date.now() });
    }
  };

  const onAuthorized = useCallback((pledge: PublicPledge) => {
    updatePledge(pledge);
    setPaypalNote("authorized");
    void refresh();
  }, [refresh, updatePledge]);

  useEffect(() => {
    if (!treasurerOpen) return undefined;
    let cancelled = false;
    void fetchFeatures()
      .then((flags) => {
        if (!cancelled) setClockPinned(Boolean(flags.clock_pinned));
      })
      .catch(() => {
        if (!cancelled) setClockPinned(false);
      });
    return () => {
      cancelled = true;
    };
  }, [treasurerOpen]);

  useEffect(() => {
    if (!treasurerOpen) return undefined;
    let cancelled = false;
    void fetchFund("project", adminKey)
      .then((row) => {
        if (!cancelled) setProjectFund(row);
      })
      .catch(() => {
        if (!cancelled) setProjectFund(null);
      });
    void fetchFund("fund", adminKey)
      .then((row) => {
        if (!cancelled) setBoatFund(row);
      })
      .catch(() => {
        if (!cancelled) setBoatFund(null);
      });
    return () => {
      cancelled = true;
    };
  }, [treasurerOpen, pledges, adminKey]);

  useEffect(() => {
    const onHash = () => setHash(window.location.hash);
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const pledgeQueueRef = useRef({ updatePledge, refresh });
  pledgeQueueRef.current = { updatePledge, refresh };

  useEffect(() => {
    const vaultParsed = readVaultReturn(window.location.search);
    if (vaultParsed) {
      const next = new URL(window.location.href);
      next.searchParams.delete("vault");
      next.searchParams.delete("pledge_id");
      next.searchParams.delete("token");
      next.searchParams.delete("approval_token_id");
      next.searchParams.delete("approval_session_id");
      window.history.replaceState({}, "", `${next.pathname}${next.search}${next.hash}`);
      if (vaultParsed.action === "cancel") {
        setPaypalNote("vaultRetry");
        if (vaultParsed.pledgeId) {
          emitPledgeReturn({ pledgeId: vaultParsed.pledgeId, outcome: "cancel" });
        }
        return undefined;
      }
      if (!vaultParsed.pledgeId) return undefined;
      setPaypalNote("vaulting");
      void registerVault(vaultParsed.pledgeId, vaultParsed.approvalTokenId)
        .then((pledge) => {
          pledgeQueueRef.current.updatePledge(pledge);
          void pledgeQueueRef.current.refresh();
          setPaypalNote("vaultSaved");
          setHealthOk(true);
          emitPledgeReturn({ pledgeId: vaultParsed.pledgeId, outcome: "authorized" });
        })
        .catch(() => {
          setPaypalNote("vaultFailed");
          emitPledgeReturn({ pledgeId: vaultParsed.pledgeId, outcome: "error" });
        });
      return undefined;
    }

    const parsed = readPaypalReturn(window.location.search);
    if (!parsed) return undefined;
    const next = new URL(window.location.href);
    next.searchParams.delete("paypal");
    next.searchParams.delete("pledge_id");
    next.searchParams.delete("token");
    next.searchParams.delete("PayerID");
    window.history.replaceState({}, "", `${next.pathname}${next.search}${next.hash}`);
    if (parsed.action === "cancel") {
      setPaypalNote("cancel");
      if (parsed.pledgeId) {
        emitPledgeReturn({ pledgeId: parsed.pledgeId, outcome: "cancel" });
      }
      return undefined;
    }
    if (!parsed.pledgeId) return;
    setPaypalNote("authorizing");
    void authorizePledge(parsed.pledgeId)
      .then((pledge) => {
        pledgeQueueRef.current.updatePledge(pledge);
        void pledgeQueueRef.current.refresh();
        setPaypalNote("authorized");
        setHealthOk(true);
        emitPledgeReturn({ pledgeId: parsed.pledgeId, outcome: "authorized" });
      })
      .catch((err: unknown) => {
        const message = err instanceof Error ? err.message : String(err);
        setPaypalNote(message);
        emitPledgeReturn({ pledgeId: parsed.pledgeId, outcome: "error", message });
      });
  }, []);

  const onKind = (next: string) => {
    setKind(next);
    const priced = KIND_AMOUNT[next];
    if (priced) setAmount(priced);
    else if (next === "mile") setAmount("1.00");
  };

  const onSettle = async () => {
    const key = adminKey.trim();
    if (!key) return;
    setSettleBusy(true);
    setSettleNote(null);
    try {
      await settleClock(key);
      setSettleNote(t("treasurer.settleDone"));
    } catch (err: unknown) {
      setSettleNote(err instanceof Error ? err.message : String(err));
    } finally {
      setSettleBusy(false);
    }
  };

  const onSettleAt = async () => {
    const key = adminKey.trim();
    const raw = settleAt.trim();
    if (!key || !raw) return;
    setSettleBusy(true);
    setSettleNote(null);
    try {
      const parsed = new Date(raw);
      if (Number.isNaN(parsed.getTime())) {
        throw new Error(t("treasurer.settleAtInvalid"));
      }
      const iso = parsed.toISOString().replace(/\.\d{3}Z$/, "Z");
      await settleClock(key, iso);
      setSettleNote(t("treasurer.settleDone"));
    } catch (err: unknown) {
      setSettleNote(err instanceof Error ? err.message : String(err));
    } finally {
      setSettleBusy(false);
    }
  };

  const onSpend = async () => {
    if (!adminKey.trim() || !milestoneId) return;
    setSpendError(null);
    try {
      const row = await recordSpending(
        milestoneId,
        { amount_eur: spendAmount, description: spendNote },
        adminKey.trim(),
      );
      setFund(row);
      setSpendNote("");
    } catch (err: unknown) {
      setSpendError(err instanceof Error ? err.message : String(err));
    }
  };

  const onSuggested = (pledge: CaptainChatResponse["suggested_pledge"]) => {
    if (!pledge) return;
    setAmount(pledge.amount_eur);
    setMilestoneId(pledge.milestone_id);
    if (pledge.kind) setKind(pledge.kind);
  };

  useEffect(() => {
    if (tab === "marinas" && prevTabRef.current !== "marinas" && voyage?.stops?.length) {
      const next = nextStopover(voyage.stops, cumNm);
      if (next) chooseStop(next);
    }
    prevTabRef.current = tab;
  }, [tab, voyage?.stops, cumNm]);

  const marinaFeatures = ficheMarinas(fiche);
  const onFlyTo = (_id: string, lat: number, lon: number) => {
    setFlyTo({ lat, lon, ts: Date.now() });
  };

  const paypalNotices = (
    <>
      {healthOk === false ? <p className="notice error">{t("app.healthFail")}</p> : null}
      {paypalNote === "cancel" ? <p className="notice warn">{t("pledge.cancelled")}</p> : null}
      {paypalNote === "vaultCancel" ? <p className="notice warn">{t("pledge.vaultCancelled")}</p> : null}
      {paypalNote === "vaultRetry" ? <p className="notice warn">{t("pledge.vaultRetry")}</p> : null}
      {paypalNote === "authorizing" ? <p className="status">{t("pledge.authorizing")}</p> : null}
      {paypalNote === "vaulting" ? <p className="status">{t("pledge.vaulting")}</p> : null}
      {paypalNote === "authorized" ? <p className="status">{t("pledge.authorized")}</p> : null}
      {paypalNote === "vaulted" ? <p className="status">{t("pledge.vaultSaved")}</p> : null}
      {paypalNote === "vaultSaved" ? <p className="status">{t("pledge.vaultSaved")}</p> : null}
      {paypalNote === "vaultFailed" ? <p className="notice error">{t("pledge.vaultFailed")}</p> : null}
      {paypalNote &&
      paypalNote !== "cancel" &&
      paypalNote !== "vaultCancel" &&
      paypalNote !== "vaultRetry" &&
      paypalNote !== "authorizing" &&
      paypalNote !== "vaulting" &&
      paypalNote !== "authorized" &&
      paypalNote !== "vaulted" &&
      paypalNote !== "vaultSaved" &&
      paypalNote !== "vaultFailed" ? (
        <p className="notice error">{paypalNote}</p>
      ) : null}
    </>
  );

  return (
    <div className="ng-shell" data-testid="ng-shell">
      <div className="ng-map-layer">
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
          onFlyTo={onFlyTo}
          onSelectProject={(props: { id?: string }) => {
            if (props?.id) setSelectedProjectId(props.id);
          }}
        />
      </div>

      <div className="ng-notices">{paypalNotices}</div>

      <aside
        className={`ng-sidebar panel${sidebarOpen ? "" : " ng-collapsed"}`}
        data-testid="ng-sidebar"
      >
        <button
          type="button"
          className="ng-sidebar-toggle"
          data-testid="ng-sidebar-toggle"
          aria-expanded={sidebarOpen}
          onClick={() => setSidebarOpen((open) => !open)}
        >
          {sidebarOpen ? "◀" : "▶"}
        </button>
        <div className="ng-shell-header">
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
        <div className="ng-tab-bar tab-bar" role="tablist">
          <button type="button" role="tab" aria-selected={tab === "voyage"} className={tab === "voyage" ? "active" : ""} onClick={() => setTab("voyage")}>
            {t("tabs.voyage")}
          </button>
          <button type="button" role="tab" aria-selected={tab === "marinas"} className={tab === "marinas" ? "active" : ""} onClick={() => setTab("marinas")}>
            {t("tabs.marinas")}
          </button>
        </div>
        <p className="ng-clock-line voyage-clock" data-testid="voyage-clock">
          {formatCivilDate(sample?.iso, lang)}
          {" · "}
          {t("clock.sailed", { nm: Number.isFinite(cumNm) ? cumNm.toFixed(1) : "—" })}
          {" "}
          {t("clock.simulated")}
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
        <section className="crew-supporter-public" data-testid="crew-supporter-public">
          <CrewSubscribeButton adminKey={adminKey.trim() || undefined} />
        </section>
        {tab === "voyage" ? (
          <>
            <ProjectList
              projects={projects}
              selectedProjectId={selectedProjectId}
              onSelectProject={setSelectedProjectId}
              contributor={contributor}
              onFlyTo={onFlyTo}
              onAuthorized={onAuthorized}
            />
            <EscalesPanel
              milestoneId={milestoneId}
              onMilestoneId={setMilestoneId}
              onSuggested={onSuggested}
              onAuthorized={onAuthorized}
            />
          </>
        ) : (
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
        )}
        <TreasurerPanel
          open={treasurerOpen}
          onOpenChange={setTreasurerOpen}
          adminKey={adminKey}
          onAdminKeyChange={setAdminKey}
          settleBusy={settleBusy}
          settleNote={settleNote}
          onSettle={() => void onSettle()}
          clockPinned={clockPinned}
          settleAt={settleAt}
          onSettleAtChange={setSettleAt}
          onSettleAt={() => void onSettleAt()}
          milestoneId={milestoneId}
          onMilestoneIdChange={setMilestoneId}
          projectFund={projectFund}
          boatFund={boatFund}
          pledges={pledges}
          loading={loading}
          error={error}
          needsKey={needsKey}
          onRefreshQueue={() => void refresh()}
          onPledgeUpdated={updatePledge}
          spendAmount={spendAmount}
          onSpendAmountChange={setSpendAmount}
          spendNote={spendNote}
          onSpendNoteChange={setSpendNote}
          spendError={spendError}
          fund={fund}
          onSpendSubmit={(event) => {
            event.preventDefault();
            void onSpend();
          }}
        />
      </aside>

      <aside className="ng-tools-panel panel" data-testid="ng-tools-panel">
        {tab === "voyage" ? (
          stop ? (
            <EscalePopup
              stop={stop}
              fiche={fiche}
              loading={ficheLoading}
              error={ficheError}
              onClose={() => setStop(null)}
              pledge={{
                amount,
                milestoneId,
                contributor,
                kind,
                onAmount: setAmount,
                onMilestoneId: setMilestoneId,
                onContributor: setContributor,
                onKind,
              }}
              onPledgeAuthorized={onAuthorized}
            />
          ) : (
            <p className="hint">{t("sheet.pick")}</p>
          )
        ) : (
          <MarinasPanel
            marinas={marinaFeatures}
            onFlyTo={onFlyTo}
            milestoneId={milestoneId}
            contributor={contributor}
            onAuthorized={onAuthorized}
          />
        )}
      </aside>
    </div>
  );
}

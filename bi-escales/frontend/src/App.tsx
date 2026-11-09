import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { formatSettleCaptureNote } from "./api/settleCaptureNote";
import { approveCrewSubscription, authorizePledge, fetchCrewSupporterPlan, fetchFund, fetchFeatures, fetchGearProjects, fetchHealthRetrying, fetchPrices, fetchPublicCommonFund, fetchSchedule, readCrewSubscribeReturn, readPaypalReturn, readVaultReturn, recordSpending, registerVault, settleClock } from "./api/escales";
import { emitCrewSubscribeReturn } from "./paypal/crewSubscribeReturnEvents";
import { emitPledgeReturn } from "./paypal/pledgeReturnEvents";
import type { CaptainChatResponse, FundView, PublicPledge, ScheduleResponse } from "./api/types";
import { EscalesPanel } from "./components/EscalesPanel";
import { EscalePopup } from "./components/EscalePopup.jsx";
import MarinasPanel from "./components/MarinasPanel.jsx";
import ProjectList from "./components/ProjectList.jsx";
import { TreasurerPanel } from "./components/TreasurerPanel";
import { CrewSupporterPublicSection } from "./components/CrewSubscribeButton";
import { HowItWorks } from "./components/stop/HowItWorks.jsx";
import EscalesScheduler from "./components/escales/EscalesScheduler.jsx";
import { ToastContainer } from "./components/Toast";
import type { ToastItem } from "./components/Toast";
import { usePledgeQueue } from "./hooks/usePledgeQueue";
import { useTheme } from "./hooks/useTheme";
import { setLanguage } from "./i18n";
import { MapScene } from "./map/MapScene.jsx";
import { ficheMarinas, loadAllEscalesMarinasGeojson, loadEscaleFiche, loadEscaleMarinasGeojson } from "./marinas/escaleFiche.js";
import { useVoyageNow } from "./hooks/useVoyageNow";
import { publicCommonFundMessage } from "./utils/publicCommonFund";
import { resolveBoatStop } from "./voyage/boatStop.js";
import { fetchJson, sampleAt, voyageFromRoute } from "./voyage/loadVoyage.js";
import { resolveDepartureT0 } from "./voyage/departureT0.js";
import { isNarrowScreen } from "./utils/narrowScreen";
import { formatCivilDate } from "./voyage/voyageClock.js";
import { escaleArrivalIso, logbookEntriesForStop } from "./voyage/journalDisplay.js";
import {
  amountFromSuggestedPledge,
  cabinLegMilestoneId,
  defaultAmountForKind,
} from "./pledge/stopPledgeAmount.js";
import "./styles/app.css";
import "./styles/naviguide-shell.css";

type TabId = "voyage" | "marinas" | "gear";

type VoyageStop = {
  name: string;
  lat: number;
  lon: number;
  milestoneId: string;
  flags?: string[];
};

type FlyTarget = { lat: number; lon: number; ts: number };

/** Matches GET /milestones/{id}/fund treasurer gate (aggregate project + per-project ids). */
function milestoneFundRequiresAdminKey(milestoneId: string): boolean {
  const token = milestoneId.trim().toLowerCase();
  return token === "project" || token === "projet" || token.startsWith("projet-");
}

export default function App() {
  const { t, i18n } = useTranslation();
  const { theme, toggleTheme } = useTheme();
  const [tab, setTab] = useState<TabId>("voyage");
  const [healthOk, setHealthOk] = useState<boolean | null>(null);
  const [hash, setHash] = useState(() => window.location.hash);
  const [adminKey, setAdminKey] = useState("");
  const [queueAdminKey, setQueueAdminKey] = useState("");
  const [demoTreasurerAvailable, setDemoTreasurerAvailable] = useState(false);
  const [demoTreasurer, setDemoTreasurer] = useState(false);
  useEffect(() => {
    const handle = window.setTimeout(() => setQueueAdminKey(adminKey), 350);
    return () => window.clearTimeout(handle);
  }, [adminKey]);
  const { pledges, loading, error, needsKey, refresh, updatePledge } = usePledgeQueue(
    queueAdminKey,
    demoTreasurer,
  );

  const [routeFc, setRouteFc] = useState<unknown>(null);
  const [projects, setProjects] = useState<{ features?: unknown[] }>({ features: [] });
  const [devT0, setDevT0] = useState("");
  const now = useVoyageNow();
  const judgeStopPicked = useRef(false);
  const [stop, setStop] = useState<VoyageStop | null>(null);
  const [fiche, setFiche] = useState<unknown>(null);
  const [marinaGeojson, setMarinaGeojson] = useState<unknown>(null);
  const [ficheLoading, setFicheLoading] = useState(false);
  const [ficheError, setFicheError] = useState<string | null>(null);
  const [flyTo, setFlyTo] = useState<FlyTarget | null>(null);
  const [amount, setAmount] = useState("1.00");
  const [contributor, setContributor] = useState("");
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
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
  const [publicCommonFund, setPublicCommonFund] = useState<FundView | null>(null);
  const [crewSubscribeNote, setCrewSubscribeNote] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [toolsOpen, setToolsOpen] = useState(true);
  const toolsPanelRef = useRef<HTMLElement>(null);
  const [panelFocusRequest, setPanelFocusRequest] = useState(0);
  const [allMarinas, setAllMarinas] = useState<{ type: string; features?: unknown[] }>({
    type: "FeatureCollection",
    features: [],
  });
  const [treasurerOpen, setTreasurerOpen] = useState(false);
  const [bryntumEnabled, setBryntumEnabled] = useState(false);
  const [wishlistsEnabled, setWishlistsEnabled] = useState(false);
  const [schedule, setSchedule] = useState<ScheduleResponse | null>(null);

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
  const countdownHours =
    sample?.status === "waiting" && sample.countdownHours != null
      ? Math.max(0, Math.round(Number(sample.countdownHours)))
      : null;
  const sailedNm = Number.isFinite(cumNm) ? cumNm.toFixed(1).replace(/\.0$/, "") : "—";
  const sheetArrivalIso = useMemo(
    () => (stop?.milestoneId && schedule ? escaleArrivalIso(schedule, stop.milestoneId) : ""),
    [stop?.milestoneId, schedule],
  );
  const sheetLogbook = useMemo(
    () => (stop?.milestoneId && schedule ? logbookEntriesForStop(schedule, stop.milestoneId) : []),
    [stop?.milestoneId, schedule],
  );

  useEffect(() => {
    document.body.classList.add("ng-naviguide-shell");
    return () => document.body.classList.remove("ng-naviguide-shell");
  }, []);

  useEffect(() => {
    let cancelled = false;
    void loadAllEscalesMarinasGeojson()
      .then((fc) => {
        if (!cancelled) setAllMarinas(fc as { type: string; features?: unknown[] });
      })
      .catch(() => {
        if (!cancelled) setAllMarinas({ type: "FeatureCollection", features: [] });
      });
    return () => {
      cancelled = true;
    };
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
    void fetchJson("/bi-projects.geojson")
      .then((base) => {
        if (cancelled) return;
        void fetchGearProjects().then((gear) => {
          if (cancelled) return;
          const baseFeatures = Array.isArray((base as { features?: unknown[] })?.features)
            ? (base as { features: unknown[] }).features
            : [];
          const gearFeatures = Array.isArray(gear?.features) ? gear.features : [];
          const seen = new Set(
            gearFeatures
              .map((row) => String((row as { properties?: { id?: string } })?.properties?.id || ""))
              .filter(Boolean),
          );
          const merged = [
            ...gearFeatures,
            ...baseFeatures.filter((row) => {
              const id = String((row as { properties?: { id?: string } })?.properties?.id || "");
              return !id || !seen.has(id);
            }),
          ];
          setProjects({ ...(base as object), features: merged });
        }).catch(() => {
          if (!cancelled) setProjects(base as { features?: unknown[] });
        });
      })
      .catch(() => setProjects({ features: [] }));
    void fetchFeatures()
      .then((flags) => {
        if (cancelled) return;
        setBryntumEnabled(Boolean(flags.bryntum));
        setWishlistsEnabled(Boolean(flags.wishlists));
        setClockPinned(Boolean(flags.clock_pinned));
        setDemoTreasurerAvailable(Boolean(flags.demo_treasurer));
      })
      .catch(() => {
        if (!cancelled) {
          setBryntumEnabled(false);
          setClockPinned(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    void fetchSchedule()
      .then((row) => {
        if (!cancelled) setSchedule(row);
      })
      .catch(() => {
        if (!cancelled) setSchedule(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    void fetchPrices(lang)
      .then((prices) => {
        if (!cancelled) {
          setSchedule((prev) => (prev ? { ...prev, prices } : prev));
        }
      })
      .catch(() => {
        /* keep schedule-embedded catalogue when /prices fails */
      });
    return () => {
      cancelled = true;
    };
  }, [lang]);

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
    if (!stop) {
      setMarinaGeojson(null);
      return undefined;
    }
    let cancelled = false;
    void loadEscaleMarinasGeojson(stop)
      .then((fc) => {
        if (!cancelled) setMarinaGeojson(fc);
      })
      .catch(() => {
        if (!cancelled) setMarinaGeojson({ type: "FeatureCollection", features: [] });
      });
    return () => {
      cancelled = true;
    };
  }, [stop]);

  useEffect(() => {
    if (hash === "#tresorier") {
      setTreasurerOpen(true);
      setSidebarOpen(true);
    }
  }, [hash]);

  const onTreasurerOpenChange = useCallback((open: boolean) => {
    setTreasurerOpen(open);
    if (!open) {
      setDemoTreasurer(false);
    }
    if (!open && window.location.hash === "#tresorier") {
      const next = `${window.location.pathname}${window.location.search}`;
      window.history.replaceState({}, "", next);
      setHash("");
    }
  }, []);

  useEffect(() => {
    if (!treasurerOpen || demoTreasurer || !milestoneId) {
      if (!treasurerOpen) setFund(null);
      return undefined;
    }
    const key = adminKey.trim();
    if (milestoneFundRequiresAdminKey(milestoneId) && !key) {
      setFund(null);
      return undefined;
    }
    let cancelled = false;
    void fetchFund(milestoneId, key || undefined)
      .then((row) => {
        if (!cancelled) setFund(row);
      })
      .catch(() => {
        if (!cancelled) setFund(null);
      });
    return () => {
      cancelled = true;
    };
  }, [milestoneId, pledges, treasurerOpen, adminKey, demoTreasurer]);

  const startDemoTreasurer = useCallback(() => {
    setAdminKey("");
    setDemoTreasurer(true);
    setTreasurerOpen(true);
  }, []);

  // After the render, because the panel may only just have reopened.
  useEffect(() => {
    if (panelFocusRequest) toolsPanelRef.current?.focus({ preventScroll: true });
  }, [panelFocusRequest]);

  const chooseStop = (next: VoyageStop) => {
    setStop(next);
    setMilestoneId(next.milestoneId);
    if (tab !== "voyage") setTab("voyage");
    if (isNarrowScreen()) {
      setSidebarOpen(false);
      setToolsOpen(true);
      setPanelFocusRequest((count) => count + 1);
    }
    if (Number.isFinite(next.lat) && Number.isFinite(next.lon)) {
      setFlyTo({ lat: next.lat, lon: next.lon, ts: Date.now() });
    }
  };

  useEffect(() => {
    if (!clockPinned || !voyage?.stops?.length || !sample || judgeStopPicked.current || stop) return;
    const target = resolveBoatStop(voyage.stops, sample);
    if (!target) return;
    judgeStopPicked.current = true;
    chooseStop(target);
  }, [clockPinned, voyage, sample, stop]);

  const locateBoat = useCallback(() => {
    const target = resolveBoatStop(voyage?.stops, sample);
    if (!target) return;
    chooseStop(target);
    if (sample && Number.isFinite(sample.lat) && Number.isFinite(sample.lon)) {
      setFlyTo({ lat: sample.lat, lon: sample.lon, ts: Date.now() });
    }
  }, [voyage?.stops, sample]);

  const onSchedulePick = (event: { milestoneId?: string; lat?: number; lon?: number; name?: string }) => {
    if (!event?.milestoneId) return;
    const match = (voyage?.stops || []).find((row: VoyageStop) => row.milestoneId === event.milestoneId);
    if (match) {
      chooseStop(match);
      return;
    }
    chooseStop({
      name: event.name || event.milestoneId,
      lat: Number(event.lat) || 0,
      lon: Number(event.lon) || 0,
      milestoneId: event.milestoneId,
    });
  };

  const onAuthorized = useCallback((pledge: PublicPledge) => {
    updatePledge(pledge);
    setPaypalNote("authorized");
    void refresh();
  }, [refresh, updatePledge]);

  useEffect(() => {
    let cancelled = false;
    void fetchPublicCommonFund().then((row) => {
      if (!cancelled) {
        setPublicCommonFund(row);
        setBoatFund((prev) => (prev === undefined ? row : prev));
      }
    });
    return () => {
      cancelled = true;
    };
  }, [pledges.length]);

  useEffect(() => {
    if (!treasurerOpen || demoTreasurer) return undefined;
    let cancelled = false;
    const key = adminKey.trim();
    if (key) {
      void fetchFund("project", key)
        .then((row) => {
          if (!cancelled) setProjectFund(row);
        })
        .catch(() => {
          if (!cancelled) setProjectFund(null);
        });
    }
    void fetchPublicCommonFund()
      .then((row) => {
        if (!cancelled) setBoatFund(row);
      })
      .catch(() => {
        if (!cancelled) setBoatFund(null);
      });
    return () => {
      cancelled = true;
    };
  }, [treasurerOpen, pledges, adminKey, demoTreasurer]);

  useEffect(() => {
    const onHash = () => setHash(window.location.hash);
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const pledgeQueueRef = useRef({ updatePledge, refresh });
  pledgeQueueRef.current = { updatePledge, refresh };

  useEffect(() => {
    const crewParsed = readCrewSubscribeReturn(window.location.search, window.location.hash);
    if (crewParsed) {
      const next = new URL(window.location.href);
      next.searchParams.delete("sub");
      next.searchParams.delete("subscription_id");
      next.searchParams.delete("ba_token");
      next.searchParams.delete("token");
      if (next.hash === "#crew-subscribe=return" || next.hash === "#crew-subscribe=cancel") {
        next.hash = "";
      }
      window.history.replaceState({}, "", `${next.pathname}${next.search}${next.hash}`);
      setHash(next.hash);
      if (crewParsed.action === "cancel") {
        setCrewSubscribeNote("cancelled");
        emitCrewSubscribeReturn({ outcome: "cancel" });
        return undefined;
      }
      setCrewSubscribeNote("verifying");
      void (async () => {
        const subscriptionId = crewParsed.subscriptionId?.trim();
        try {
          const planBody = await fetchCrewSupporterPlan();
          const planId = String(planBody.plan_id || "").trim();
          if (!subscriptionId || !planId) {
            setCrewSubscribeNote("pending");
            emitCrewSubscribeReturn({ outcome: "pending" });
            return;
          }
          await approveCrewSubscription({ subscription_id: subscriptionId, plan_id: planId });
          setCrewSubscribeNote("confirmed");
          emitCrewSubscribeReturn({ outcome: "confirmed" });
        } catch {
          setCrewSubscribeNote("pending");
          emitCrewSubscribeReturn({ outcome: "pending" });
        }
      })();
      return undefined;
    }

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
    const priced = defaultAmountForKind(next, schedule?.prices);
    if (priced) setAmount(priced);
    if (next === "cabin_leg" && stop?.milestoneId) {
      const legId = cabinLegMilestoneId(schedule, stop.milestoneId, stop.name);
      if (legId) setMilestoneId(legId);
    } else if (stop?.milestoneId && next !== "cabin_leg") {
      setMilestoneId(stop.milestoneId);
    }
  };

  const runSettle = async (atIso?: string) => {
    const key = adminKey.trim();
    if (!key) return;
    setSettleBusy(true);
    setSettleNote(null);
    try {
      const body = atIso?.trim()
        ? await settleClock(key, atIso)
        : await settleClock(key);
      await refresh();
      setSettleNote(formatSettleCaptureNote(t, body.settled));
    } catch (err: unknown) {
      setSettleNote(err instanceof Error ? err.message : String(err));
    } finally {
      setSettleBusy(false);
    }
  };

  const onSettle = async () => {
    await runSettle();
  };

  const onSettleAt = async () => {
    const raw = settleAt.trim();
    if (!raw) return;
    const parsed = new Date(raw);
    if (Number.isNaN(parsed.getTime())) {
      setSettleNote(t("treasurer.settleAtInvalid"));
      return;
    }
    const iso = parsed.toISOString().replace(/\.\d{3}Z$/, "Z");
    await runSettle(iso);
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
    const nextKind = pledge.kind || kind;
    setKind(nextKind);
    setAmount(amountFromSuggestedPledge(pledge, schedule?.prices));
    if (nextKind === "cabin_leg" && stop?.milestoneId) {
      const legId = cabinLegMilestoneId(schedule, stop.milestoneId, stop.name);
      setMilestoneId(legId || pledge.milestone_id);
    } else {
      setMilestoneId(pledge.milestone_id);
    }
  };

  // Prefer the all-stops marina catalog so the zoomed-out map always shows dots.
  // Per-stop geojson remains available for the tools panel when a stop is open.
  const stopMarinaFeatures =
    (marinaGeojson as { features?: unknown[] } | null) ?? ficheMarinas(fiche);
  const marinaFeatures =
    Array.isArray(allMarinas?.features) && allMarinas.features.length > 0
      ? allMarinas
      : stopMarinaFeatures;
  const onFlyTo = (_id: string, lat: number, lon: number) => {
    setFlyTo({ lat, lon, ts: Date.now() });
  };

  const dismissToast = useCallback((id: string) => {
    if (id.startsWith("paypal-")) setPaypalNote(null);
    if (id.startsWith("crew-")) setCrewSubscribeNote(null);
    if (id.startsWith("health-")) setHealthOk(null);
  }, []);

  const toastItems = useMemo(() => {
    const items: ToastItem[] = [];
    const push = (variant: ToastItem["variant"], title: string, opts?: { testId?: string; detail?: string; idPrefix?: string; key?: string }) => {
      const prefix = opts?.idPrefix ?? "paypal";
      items.push({
        id: `${prefix}-${opts?.key ?? variant}-${title}`,
        variant,
        title,
        detail: opts?.detail,
        testId: opts?.testId,
      });
    };

    // Newest on top: user transaction feedback above system health
    if (paypalNote === "cancel") push("warn", t("pledge.cancelled"), { key: "cancel" });
    else if (paypalNote === "vaultCancel") push("warn", t("pledge.vaultCancelled"), { key: "vaultCancel" });
    else if (paypalNote === "vaultRetry") push("warn", t("pledge.vaultRetry"), { key: "vaultRetry" });
    else if (paypalNote === "authorizing") push("info", t("pledge.authorizing"), { key: "authorizing" });
    else if (paypalNote === "vaulting") push("info", t("pledge.vaulting"), { key: "vaulting" });
    else if (paypalNote === "authorized") push("held", t("pledge.authorized"), { key: "authorized" });
    else if (paypalNote === "vaulted") push("success", t("pledge.vaultSaved"), { key: "vaulted" });
    else if (paypalNote === "vaultSaved") push("success", t("pledge.vaultSaved"), { key: "vaultSaved" });
    else if (paypalNote === "vaultFailed") push("error", t("pledge.vaultFailed"), { key: "vaultFailed" });
    else if (paypalNote) push("error", paypalNote, { key: "custom" });

    if (crewSubscribeNote === "verifying") {
      push("info", t("pledge.crewSubscribeVerifying"), { testId: "crew-subscribe-return-notice", idPrefix: "crew", key: "verifying" });
    } else if (crewSubscribeNote === "confirmed") {
      push("success", t("pledge.crewSubscribeConfirmed"), { testId: "crew-subscribe-return-notice", idPrefix: "crew", key: "confirmed" });
    } else if (crewSubscribeNote === "pending") {
      push("warn", t("pledge.crewSubscribePending"), { testId: "crew-subscribe-return-notice", idPrefix: "crew", key: "pending" });
    } else if (crewSubscribeNote === "cancelled") {
      push("warn", t("pledge.crewSubscribeCancelled"), { testId: "crew-subscribe-cancel-notice", idPrefix: "crew", key: "cancelled" });
    }

    if (healthOk === false) {
      push("error", t("app.healthFail"), { idPrefix: "health", key: "fail" });
    }

    return items;
  }, [healthOk, crewSubscribeNote, paypalNote, t]);

  const mapProjects = useMemo(() => {
    const all = Array.isArray(projects?.features) ? projects.features : [];
    const isGear = (row: unknown) =>
      String((row as { properties?: { project_kind?: string } })?.properties?.project_kind || "") === "gear_project";
    if (tab === "gear") {
      return { ...projects, features: all.filter((row) => isGear(row)) };
    }
    if (tab === "voyage") {
      return { ...projects, features: all.filter((row) => !isGear(row)) };
    }
    return { ...projects, features: [] };
  }, [projects, tab]);

  const treasurerPanel = (
    <TreasurerPanel
      open={treasurerOpen}
      onOpenChange={onTreasurerOpenChange}
      demoMode={demoTreasurer}
      demoStopAvailable={demoTreasurerAvailable}
      adminKey={adminKey}
      onAdminKeyChange={setAdminKey}
      settleBusy={settleBusy}
      settleNote={settleNote}
      onSettle={() => void onSettle()}
      clockPinned={clockPinned}
      schedule={schedule}
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
    >
      {demoTreasurerAvailable ? (
        <button
          type="button"
          className="secondary demo-treasurer-entry"
          data-testid="demo-treasurer-button"
          onClick={() => startDemoTreasurer()}
        >
          {t("treasurer.demoButton")}
        </button>
      ) : null}
    </TreasurerPanel>
  );

  return (
    <div className="ng-shell" data-testid="ng-shell">
      <div className="ng-map-layer">
        <MapScene
          segments={voyage?.segments || []}
          stops={voyage?.stops || []}
          boat={sample && Number.isFinite(sample.lat) ? { lat: sample.lat, lon: sample.lon, bearing: sample.bearing } : null}
          projects={mapProjects}
          marinas={marinaFeatures}
          showProjects={tab === "voyage" || tab === "gear"}
          showMarinas={tab === "marinas"}
          flyTo={flyTo}
          theme={theme}
          onSelectStop={chooseStop}
          onSelectBoat={locateBoat}
          onFlyTo={onFlyTo}
          contributor={contributor}
          onPledgeAuthorized={onAuthorized}
          marinaMilestoneId={milestoneId}
          onSelectProject={(props: { id?: string }) => {
            if (props?.id) setSelectedProjectId(props.id);
          }}
        />
        <button
          type="button"
          className={`ng-sidebar-toggle ng-sidebar-toggle--left${sidebarOpen ? " is-open" : ""}`}
          data-testid="ng-sidebar-toggle"
          aria-expanded={sidebarOpen}
          aria-label={sidebarOpen ? t("app.sidebarCollapse") : t("app.sidebarExpand")}
          onClick={() => setSidebarOpen((open) => !open)}
        >
          {sidebarOpen ? "◀" : "▶"}
        </button>

        <button
          type="button"
          className={`ng-tools-toggle ng-tools-toggle--right${toolsOpen ? " is-open" : ""}`}
          data-testid="ng-tools-toggle"
          aria-expanded={toolsOpen}
          aria-label={toolsOpen ? t("app.toolsCollapse") : t("app.toolsExpand")}
          onClick={() => setToolsOpen((open) => !open)}
        >
          {toolsOpen ? "▶" : "⚙"}
        </button>
      </div>

      <ToastContainer items={toastItems} onDismiss={dismissToast} />


      <aside
        className={`ng-sidebar panel${sidebarOpen ? "" : " ng-collapsed"}`}
        data-testid="ng-sidebar"
      >
        <div className="rail-masthead">
          <div className="ng-shell-header">
            <svg className="voyage-emblem" width="32" height="32" viewBox="0 0 32 32" fill="none" aria-hidden="true">
              <path d="M16 3v19H5L16 3Z" fill="currentColor" />
              <path d="m19 8 8 14h-8V8Z" fill="currentColor" opacity=".6" />
              <path d="M4 25h24l-5 4H9l-5-4Z" fill="currentColor" />
            </svg>
            <h1 aria-label={t("app.title")}>
              BI Escales <small>{t("app.subtitle")}</small>
            </h1>
          </div>
          <div className="ng-controls">
            <div className="lang-switch" role="group" aria-label={t("app.language")}>
              <button
                type="button"
                className={i18n.language === "fr" ? "active" : ""}
                aria-label={t("app.langFr")}
                aria-pressed={i18n.language === "fr"}
                onClick={() => setLanguage("fr")}
              >
                FR
              </button>
              <button
                type="button"
                className={i18n.language === "en" ? "active" : ""}
                aria-label={t("app.langEn")}
                aria-pressed={i18n.language === "en"}
                onClick={() => setLanguage("en")}
              >
                EN
              </button>
            </div>
            <div className="theme-switch" data-testid="theme-switch">
              <button
                type="button"
                data-testid="theme-toggle"
                aria-label={theme === "light" ? t("app.themeDark") : t("app.themeLight")}
                aria-pressed={theme === "light"}
                onClick={() => toggleTheme()}
              >
                <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                  {theme === "light" ? (
                    <path
                      d="M20.2 15.1A8.4 8.4 0 0 1 8.9 3.8 8.5 8.5 0 1 0 20.2 15.1Z"
                      stroke="currentColor"
                      strokeWidth="1.7"
                      strokeLinejoin="round"
                    />
                  ) : (
                    <>
                      <circle cx="12" cy="12" r="4" stroke="currentColor" strokeWidth="1.7" />
                      <path d="M12 2v2m0 16v2M4.93 4.93l1.42 1.42m11.3 11.3 1.42 1.42M2 12h2m16 0h2M4.93 19.07l1.42-1.42m11.3-11.3 1.42-1.42" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
                    </>
                  )}
                </svg>
              </button>
            </div>
          </div>
        </div>
        <div className="ng-tab-bar" role="tablist">
          <button type="button" role="tab" aria-selected={tab === "voyage"} className={tab === "voyage" ? "active" : ""} onClick={() => setTab("voyage")}>
            {t("tabs.voyage")}
          </button>
          <button type="button" role="tab" aria-selected={tab === "marinas"} className={tab === "marinas" ? "active" : ""} onClick={() => setTab("marinas")}>
            {t("tabs.marinas")}
          </button>
          <button type="button" role="tab" aria-selected={tab === "gear"} className={tab === "gear" ? "active" : ""} onClick={() => setTab("gear")}>
            {t("tabs.gear")}
          </button>
        </div>
        {wishlistsEnabled ? (
          <p className="wishlists-nav" data-testid="wishlists-nav-link">
            <a href="/escales/wishlists">{t("wishlists.navLink")}</a>
          </p>
        ) : null}
        <p className="ng-clock-line voyage-clock" data-testid="voyage-clock">
          {countdownHours !== null ? (
            <span className="voyage-clock-countdown">
              {t("clock.waiting", {
                days: Math.floor(countdownHours / 24),
                hours: countdownHours % 24,
              })}
            </span>
          ) : null}
          <span className="voyage-clock-date">{formatCivilDate(sample?.iso, lang)}</span>
          <span className="voyage-clock-distance">
            {t("clock.sailed", { nm: sailedNm })} · {t("clock.simulated")}
          </span>
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
          <>
            <EscalesPanel
              milestoneId={milestoneId}
              adminKey={adminKey.trim() || undefined}
              onMilestoneId={setMilestoneId}
              onSuggested={onSuggested}
              onAuthorized={onAuthorized}
              onLocateBoat={locateBoat}
            />
            {publicCommonFund ? (
              <p className="hint public-common-fund" data-testid="public-common-fund">
                {publicCommonFundMessage(publicCommonFund, lang, t)}
              </p>
            ) : null}
            {treasurerPanel}
            <CrewSupporterPublicSection adminKey={adminKey.trim() || undefined} />
            <ProjectList
              projects={projects}
              featureScope="projects"
              selectedProjectId={selectedProjectId}
              onSelectProject={setSelectedProjectId}
              contributor={contributor}
              onFlyTo={onFlyTo}
              onAuthorized={onAuthorized}
            />
            {bryntumEnabled && schedule ? (
              <EscalesScheduler
                schedule={schedule}
                planningEnabled
                onSelectEscale={onSchedulePick}
                onAuthorized={onAuthorized}
              />
            ) : null}
          </>
        ) : null}
        {tab !== "voyage" ? treasurerPanel : null}
        {tab === "marinas" ? (
          <MarinasPanel
            marinas={marinaFeatures}
            onFlyTo={onFlyTo}
            milestoneId={milestoneId}
            contributor={contributor}
            onAuthorized={onAuthorized}
          />
        ) : null}
        {tab === "gear" ? (
          <ProjectList
            projects={projects}
            featureScope="gear"
            selectedProjectId={selectedProjectId}
            onSelectProject={setSelectedProjectId}
            contributor={contributor}
            onFlyTo={onFlyTo}
            onAuthorized={onAuthorized}
          />
        ) : null}
      </aside>

      <aside
        ref={toolsPanelRef}
        tabIndex={-1}
        className={`ng-tools-panel${toolsOpen ? "" : " ng-collapsed"}`}
        data-testid="ng-tools-panel"
        aria-hidden={!toolsOpen}
      >
        {stop ? (
          <EscalePopup
            stop={stop}
            fiche={fiche}
            loading={ficheLoading}
            error={ficheError}
            onClose={() => setStop(null)}
            arrivalIso={sheetArrivalIso}
            logbookEntries={sheetLogbook}
            priceCatalog={schedule?.prices}
            schedule={schedule}
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
          <HowItWorks />
        )}
      </aside>
    </div>
  );
}

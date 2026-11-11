import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { formatSettleCaptureNote } from "./api/settleCaptureNote";
import { approveCrewSubscription, authorizePledge, fetchClock, fetchCrewSupporterPlan, fetchFund, fetchFeatures, fetchGearProjects, fetchHealthRetrying, fetchPrices, fetchPublicCommonFund, fetchSchedule, listMilestones, readCrewSubscribeReturn, readPaypalReturn, readVaultReturn, recordSpending, registerVault, settleClock } from "./api/escales";
import { emitCrewSubscribeReturn } from "./paypal/crewSubscribeReturnEvents";
import { emitPledgeReturn } from "./paypal/pledgeReturnEvents";
import { notePayPalJsFeatures } from "./paypal/paypalJsVersion";
import { hasAttempt, reconcileAttempt } from "./paypal/v6/checkoutAttempts";
import type { CaptainChatResponse, FundView, Milestone, PublicPledge, ScheduleResponse } from "./api/types";
import { EscalesPanel } from "./components/EscalesPanel";
import { EscalePopup } from "./components/EscalePopup.jsx";
import { MapLayerControl } from "./components/MapLayerControl";
import type { MapLayerId, MapLayers } from "./components/MapLayerControl";
import MarinasPanel from "./components/MarinasPanel.jsx";
import ExpeditionCartPanel from "./components/ExpeditionCartPanel.jsx";
import ProjectList from "./components/ProjectList.jsx";
import { TreasurerPanel } from "./components/TreasurerPanel";
import { CrewSupporterPublicSection } from "./components/CrewSubscribeButton";
import { HowItWorks } from "./components/stop/HowItWorks.jsx";
import EscalesScheduler from "./components/escales/EscalesScheduler.jsx";
import { PublicTotals } from "./components/PublicTotals";
import { ToastContainer } from "./components/Toast";
import type { ToastItem } from "./components/Toast";
import { usePledgeQueue } from "./hooks/usePledgeQueue";
import { useTheme } from "./hooks/useTheme";
import { setLanguage } from "./i18n";
import { MapScene } from "./map/MapScene.jsx";
import { ficheMarinas, loadAllEscalesMarinasGeojson, loadEscaleFiche, loadEscaleMarinasGeojson } from "./marinas/escaleFiche.js";
import { resolveBoatStop } from "./voyage/boatStop.js";
import { nextOpenStop } from "./voyage/nextStop.js";
import { fetchJson, sampleAt, voyageFromRoute } from "./voyage/loadVoyage.js";
import { resolveDepartureT0 } from "./voyage/departureT0.js";
import { isNarrowScreen } from "./utils/narrowScreen";
import { stopNamesFromStops } from "./utils/milestoneLabel";
import { formatCivilDate } from "./voyage/voyageClock.js";
import { escaleArrivalIso, logbookEntriesForStop } from "./voyage/journalDisplay.js";
import {
  amountFromSuggestedPledge,
  cabinLegMilestoneId,
  defaultAmountForKind,
} from "./pledge/stopPledgeAmount.js";
import "./styles/app.css";
import "./styles/naviguide-shell.css";
import "./styles/rails.css";
import "./styles/map-overlays.css";
import "./styles/mobile.css";

type TabId = "voyage" | "marinas" | "gear";

type VoyageStop = {
  name: string;
  lat: number;
  lon: number;
  milestoneId: string;
  flags?: string[];
};

type FlyTarget = { id?: string; lat: number; lon: number; ts: number };

/** Matches GET /milestones/{id}/fund treasurer gate (aggregate project + per-project ids). */
function milestoneFundRequiresAdminKey(milestoneId: string): boolean {
  const token = milestoneId.trim().toLowerCase();
  return token === "project" || token === "projet" || token.startsWith("projet-");
}

// Gear tab (Channel3 items placed on the map) stays hidden until local products tied to
// stops are built (Clément, 10 Nov). The code is kept; the wishlist link stays visible.
const GEAR_TAB_VISIBLE = false;

export default function App() {
  const { t, i18n } = useTranslation();
  const { theme, toggleTheme } = useTheme();
  const [tab, setTab] = useState<TabId>("voyage");
  // One map: projects and marinas are layers the visitor switches, not a property of the tab.
  const [layers, setLayers] = useState<MapLayers>({ projects: true, marinas: true });
  const toggleLayer = useCallback(
    (id: MapLayerId) => setLayers((current) => ({ ...current, [id]: !current[id] })),
    [],
  );
  const selectTab = useCallback((next: TabId) => {
    setTab(next);
    // The Marinas list is about what the layer draws, so opening it shows the layer.
    if (next === "marinas") {
      setLayers((current) => (current.marinas ? current : { ...current, marinas: true }));
    }
  }, []);
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
  const [now, setNow] = useState(() => new Date());
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
  // On a phone the map comes first: both panels start closed and open on demand.
  const [sidebarOpen, setSidebarOpen] = useState(() => !isNarrowScreen());
  const [toolsOpen, setToolsOpen] = useState(() => !isNarrowScreen());
  const toolsPanelRef = useRef<HTMLElement>(null);
  const [panelFocusRequest, setPanelFocusRequest] = useState(0);
  const [allMarinas, setAllMarinas] = useState<{ type: string; features?: unknown[] }>({
    type: "FeatureCollection",
    features: [],
  });
  const [treasurerOpen, setTreasurerOpen] = useState(false);
  const treasurerBackRef = useRef<HTMLButtonElement>(null);
  const [bryntumEnabled, setBryntumEnabled] = useState(false);
  const [wishlistsEnabled, setWishlistsEnabled] = useState(false);
  const [schedule, setSchedule] = useState<ScheduleResponse | null>(null);
  // False until the schedule request has answered or failed: until then the next
  // open stop is not known, and "Back the next stop" must not name one.
  const [scheduleSettled, setScheduleSettled] = useState(false);
  // The API's clock and milestones: what the stop sheet's status chip is built from.
  const [apiNow, setApiNow] = useState<string | null>(null);
  const [milestones, setMilestones] = useState<Milestone[] | null>(null);

  const prod = Boolean(import.meta.env.PROD);
  const t0 = resolveDepartureT0(prod, devT0 || undefined);
  const lang = i18n.language?.startsWith("en") ? "en" : "fr";
  const voyage = useMemo(
    () => (routeFc ? voyageFromRoute(routeFc, t0) : null),
    [routeFc, t0],
  );
  // The left rail follows the API's clock once it is known, so it cannot contradict
  // the stop statuses, which are computed from that same clock.
  const voyageNow = useMemo(() => {
    const fromApi = apiNow ? new Date(apiNow) : null;
    return fromApi && Number.isFinite(fromApi.getTime()) ? fromApi : now;
  }, [apiNow, now]);
  const sample = useMemo(
    () => (voyage ? sampleAt(voyage.clock, voyageNow) : null),
    [voyage, voyageNow],
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
        // Show the base projects at once; the gear projects join them when they arrive.
        setProjects(base as { features?: unknown[] });
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
        // Tells the PayPal buttons which browser SDK to use (v5 unless paypal_js_v6 is on).
        notePayPalJsFeatures(flags);
        if (cancelled) return;
        setBryntumEnabled(Boolean(flags.bryntum));
        setWishlistsEnabled(Boolean(flags.wishlists));
        setClockPinned(Boolean(flags.clock_pinned));
        setDemoTreasurerAvailable(Boolean(flags.demo_treasurer));
      })
      .catch(() => {
        notePayPalJsFeatures(null);
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
      })
      .finally(() => {
        if (!cancelled) setScheduleSettled(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const sync = () => {
      void fetchClock()
        .then((clock) => {
          if (!cancelled && clock?.now) setApiNow(clock.now);
        })
        .catch(() => {
          /* keep the last answer; the wall clock stands in until the first one */
        });
      void listMilestones()
        .then((rows) => {
          if (!cancelled && Array.isArray(rows)) setMilestones(rows);
        })
        .catch(() => {
          /* cancelled stops are then unknown here; the sheet still refuses them */
        });
    };
    sync();
    const id = window.setInterval(sync, 60000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
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

  useEffect(() => {
    if (treasurerOpen) treasurerBackRef.current?.focus({ preventScroll: true });
  }, [treasurerOpen]);

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

  // The default target of "back a stop": the first stop the boat has not reached and
  // that is not cancelled, by the same clock and schedule as the sheet's status chip.
  // If the schedule request failed there is no status to contradict, so the boat's
  // stop stands in. While it is still on its way, no stop is named at all: the boat's
  // stop is often one the schedule says is already reached.
  const nextStop = useMemo(
    () =>
      (schedule
        ? nextOpenStop(voyage?.stops, schedule, apiNow ?? now.toISOString(), milestones)
        : scheduleSettled
          ? resolveBoatStop(voyage?.stops, sample)
          : null) as VoyageStop | null,
    [voyage?.stops, schedule, scheduleSettled, apiNow, now, milestones, sample],
  );

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

  // Bumped after each pledge, so "Where the money goes" reads its totals again if it is open.
  const [totalsRefresh, setTotalsRefresh] = useState(0);
  const onAuthorized = useCallback((pledge: PublicPledge) => {
    updatePledge(pledge);
    setPaypalNote("authorized");
    setTotalsRefresh((count) => count + 1);
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
      // A checkout started by the v6 path shares one server reconciliation with its PayPal session.
      void (hasAttempt(vaultParsed.pledgeId)
        ? reconcileAttempt(vaultParsed.pledgeId, true, vaultParsed.approvalTokenId)
        : registerVault(vaultParsed.pledgeId, vaultParsed.approvalTokenId))
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
    void (hasAttempt(parsed.pledgeId) ? reconcileAttempt(parsed.pledgeId) : authorizePledge(parsed.pledgeId))
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
  const onFlyTo = (id: string, lat: number, lon: number) => {
    setFlyTo({ id, lat, lon, ts: Date.now() });
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
    return { ...projects, features: all.filter((row) => !isGear(row)) };
  }, [projects, tab]);

  // Channel3 pictures by gear project id, for lists that only know the id (the cart).
  const gearImages = useMemo(() => {
    const out: Record<string, string> = {};
    for (const row of Array.isArray(projects?.features) ? projects.features : []) {
      const props = (row as { properties?: { id?: string; channel3_image_url?: string | null } })?.properties;
      if (props?.id && props.channel3_image_url) out[props.id] = props.channel3_image_url;
    }
    return out;
  }, [projects]);

  // The treasurer reads stop names, not milestone ids; the voyage already has them.
  const stopNames = useMemo(() => stopNamesFromStops(voyage?.stops), [voyage?.stops]);

  // For the public totals: a project's title by id, and a stop's sheet by milestone id.
  const projectTitles = useMemo(() => {
    const out = new Map<string, string>();
    for (const row of Array.isArray(projects?.features) ? projects.features : []) {
      const props = (row as { properties?: { id?: string; title?: string } })?.properties;
      if (props?.id && props.title) out.set(String(props.id), String(props.title));
    }
    return out;
  }, [projects]);
  const projectTitle = useCallback((id: string) => projectTitles.get(id), [projectTitles]);
  const openStopById = (id: string) => {
    const match = (voyage?.stops || []).find((row: VoyageStop) => row.milestoneId === id);
    if (match) chooseStop(match);
  };

  const treasurerPanel = (
    <TreasurerPanel
      open={treasurerOpen}
      onOpenChange={onTreasurerOpenChange}
      demoMode={demoTreasurer}
      demoStopAvailable={demoTreasurerAvailable}
      stopNames={stopNames}
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
    <div
      className="ng-shell"
      data-testid="ng-shell"
      data-rail={sidebarOpen ? "open" : "closed"}
      data-sheet={toolsOpen ? "open" : "closed"}
    >
      <div className="ng-map-layer">
        <MapScene
          segments={voyage?.segments || []}
          stops={voyage?.stops || []}
          boat={sample && Number.isFinite(sample.lat) ? { lat: sample.lat, lon: sample.lon, bearing: sample.bearing } : null}
          projects={mapProjects}
          marinas={marinaFeatures}
          showProjects={layers.projects}
          showMarinas={layers.marinas}
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
        {/* Phone only, while the rail is closed (CSS): the first screen is the map, and
            without this nothing on it says which product this is. */}
        <p className="ng-map-brand" data-testid="ng-map-brand">
          <svg width="16" height="16" viewBox="0 0 32 32" fill="none" aria-hidden="true">
            <path d="M16 3v19H5L16 3Z" fill="currentColor" />
            <path d="m19 8 8 14h-8V8Z" fill="currentColor" opacity=".6" />
            <path d="M4 25h24l-5 4H9l-5-4Z" fill="currentColor" />
          </svg>
          <span>BI Escales</span>
        </p>
        <button
          type="button"
          className={`ng-sidebar-toggle ng-sidebar-toggle--left${sidebarOpen ? " is-open" : ""}`}
          data-testid="ng-sidebar-toggle"
          aria-expanded={sidebarOpen}
          aria-label={sidebarOpen ? t("app.sidebarCollapse") : t("app.sidebarExpand")}
          onClick={() => setSidebarOpen((open) => !open)}
        >
          <svg viewBox="0 0 16 16" width="16" height="16" fill="none" aria-hidden="true">
            <path d={sidebarOpen ? "m10 3.5-4.5 4.5 4.5 4.5" : "m6 3.5 4.5 4.5-4.5 4.5"} stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>

        <MapLayerControl layers={layers} onToggle={toggleLayer} />

        <button
          type="button"
          className={`ng-tools-toggle ng-tools-toggle--right${toolsOpen ? " is-open" : ""}`}
          data-testid="ng-tools-toggle"
          aria-expanded={toolsOpen}
          aria-label={toolsOpen ? t("app.toolsCollapse") : t("app.toolsExpand")}
          onClick={() => setToolsOpen((open) => !open)}
        >
          <svg viewBox="0 0 16 16" width="16" height="16" fill="none" aria-hidden="true">
            <path d={toolsOpen ? "m6 3.5 4.5 4.5-4.5 4.5" : "m10 3.5-4.5 4.5 4.5 4.5"} stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      </div>

      <ToastContainer items={toastItems} onDismiss={dismissToast} />


      <aside
        className={`ng-sidebar${sidebarOpen ? "" : " ng-collapsed"}`}
        data-testid="ng-sidebar"
      >
        <header className="rail-masthead">
          <div className="ng-shell-header">
            <svg className="voyage-emblem" width="20" height="20" viewBox="0 0 32 32" fill="none" aria-hidden="true">
              <path d="M16 3v19H5L16 3Z" fill="currentColor" />
              <path d="m19 8 8 14h-8V8Z" fill="currentColor" opacity=".6" />
              <path d="M4 25h24l-5 4H9l-5-4Z" fill="currentColor" />
            </svg>
            <h1 aria-label={t("app.title")}>BI Escales</h1>
          </div>
          <div className="ng-controls">
            <div className="lang-switch" role="group" aria-label={t("app.language")}>
              <button
                type="button"
                className={i18n.language === "fr" ? "active" : ""}
                aria-label={t("app.langFrSwitch")}
                aria-pressed={i18n.language === "fr"}
                onClick={() => setLanguage("fr")}
              >
                FR
              </button>
              <button
                type="button"
                className={i18n.language === "en" ? "active" : ""}
                aria-label={t("app.langEnSwitch")}
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
          <p className="rail-tagline">{t("app.subtitle")}</p>
        </header>
        <div className="ng-tab-bar" role="tablist">
          <button type="button" role="tab" aria-selected={tab === "voyage"} className={tab === "voyage" ? "active" : ""} onClick={() => setTab("voyage")}>
            {t("tabs.voyage")}
          </button>
          <button type="button" role="tab" aria-selected={tab === "marinas"} className={tab === "marinas" ? "active" : ""} onClick={() => selectTab("marinas")}>
            {t("tabs.marinas")}
          </button>
          {GEAR_TAB_VISIBLE && wishlistsEnabled ? (
            <button type="button" role="tab" aria-selected={tab === "gear"} className={tab === "gear" ? "active" : ""} onClick={() => setTab("gear")}>
              {t("tabs.gear")}
            </button>
          ) : null}
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
            <ProjectList
              projects={projects}
              featureScope="projects"
              selectedProjectId={selectedProjectId}
              onSelectProject={setSelectedProjectId}
              contributor={contributor}
              onFlyTo={onFlyTo}
              onAuthorized={onAuthorized}
            />
            <PublicTotals
              stopNames={stopNames}
              projectTitle={projectTitle}
              onSelectStop={openStopById}
              refreshToken={totalsRefresh}
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
        {tab === "marinas" ? (
          <MarinasPanel
            marinas={marinaFeatures}
            onFlyTo={onFlyTo}
            milestoneId={milestoneId}
            contributor={contributor}
            onAuthorized={onAuthorized}
          />
        ) : null}
        {GEAR_TAB_VISIBLE && tab === "gear" && wishlistsEnabled ? (
          <>
            <ProjectList
              projects={projects}
              featureScope="gear"
              selectedProjectId={selectedProjectId}
              onSelectProject={setSelectedProjectId}
              contributor={contributor}
              onFlyTo={onFlyTo}
              onAuthorized={onAuthorized}
            />
            <ExpeditionCartPanel images={gearImages} />
          </>
        ) : null}
        {/* Secondary to backing a stop: membership, public total, treasurer entry. */}
        <div className="rail-footer" data-testid="rail-footer">
          {tab === "voyage" ? (
            <>
              <CrewSupporterPublicSection adminKey={adminKey.trim() || undefined} />
              {publicCommonFund ? (
                <p className="hint public-common-fund" data-testid="public-common-fund">
                  {t("fund.publicCommon", {
                    balance: Number.isFinite(Number(publicCommonFund.balance_eur))
                      ? new Intl.NumberFormat(lang, {
                          style: "currency",
                          currency: publicCommonFund.currency,
                        }).format(Number(publicCommonFund.balance_eur))
                      : `${publicCommonFund.balance_eur} ${publicCommonFund.currency}`,
                  })}
                </p>
              ) : null}
            </>
          ) : null}
          {treasurerOpen ? null : treasurerPanel}
        </div>
      </aside>

      {/* Phone only (hidden by CSS on wide screens): the bottom sheet's handle. */}
      <button
        type="button"
        className="ng-sheet-handle"
        data-testid="ng-sheet-handle"
        aria-expanded={toolsOpen}
        aria-controls="ng-tools-panel"
        onClick={() => setToolsOpen((open) => !open)}
      >
        <span className="ng-sheet-grabber" aria-hidden="true" />
        <span className="ng-sheet-label">{stop ? stop.name : t("app.sheetLabel")}</span>
        <svg viewBox="0 0 16 16" width="16" height="16" fill="none" aria-hidden="true">
          <path d="m3.5 10 4.5-4.5 4.5 4.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      <aside
        ref={toolsPanelRef}
        id="ng-tools-panel"
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
          <HowItWorks
            nextStopName={nextStop?.name}
            nextStopPending={!scheduleSettled}
            onBackNextStop={nextStop ? () => chooseStop(nextStop) : undefined}
          />
        )}
      </aside>

      {treasurerOpen ? (
        <div
          className="treasurer-page"
          data-testid="treasurer-page"
          role="region"
          aria-label={t("treasurer.panelTitle")}
          onKeyDown={(event) => {
            if (event.key === "Escape") onTreasurerOpenChange(false);
          }}
        >
          <div className="treasurer-page-inner">
            <button
              type="button"
              ref={treasurerBackRef}
              className="secondary treasurer-page-back"
              data-testid="treasurer-page-back"
              onClick={() => onTreasurerOpenChange(false)}
            >
              {t("treasurer.page.back")}
            </button>
            <section className="treasurer-page-intro" data-testid="treasurer-page-intro">
              <p className="treasurer-page-eyebrow">{t("treasurer.page.eyebrow")}</p>
              <ol className="treasurer-page-steps">
                {(["propose", "decide", "settle"] as const).map((step) => (
                  <li key={step}>
                    <strong>{t(`treasurer.page.${step}Title`)}</strong>
                    <span>{t(`treasurer.page.${step}Body`)}</span>
                  </li>
                ))}
              </ol>
              <p className="hint">{t("treasurer.page.keyNote")}</p>
            </section>
            {treasurerPanel}
          </div>
        </div>
      ) : null}
    </div>
  );
}

import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { approveCrewSubscription, fetchCrewSupporterPlan, recordSubscription } from "../api/escales";
import {
  loadPayPalSubscriptionSdk,
  safePayPalClose,
  safePayPalRender,
  type PayPalNamespace,
  type PayPalSdkButtonInstance,
} from "../paypal/paypalSdk";
import { PayPalErrorBoundary } from "./PayPalErrorBoundary";
import { subscribeCrewSubscribeReturn } from "../paypal/crewSubscribeReturnEvents";
import { usePayPalJsVersion } from "../paypal/paypalJsVersion";
import { CrewSubscribeButtonV6Inner } from "./CrewSubscribeButtonV6";

export interface CrewSubscribeButtonProps {
  planId?: string;
  adminKey?: string;
  /** When true, show a neutral setup hint instead of hiding if the plan id is missing. */
  treasurerContext?: boolean;
  /** Parent renders the section heading; skip duplicate hint copy. */
  suppressHeadingHint?: boolean;
}

const PLAN_LOAD_TIMEOUT_MS = 20_000;

type ShellTheme = "light" | "dark";

/**
 * The membership is secondary to backing a stop, so its PayPal button is the
 * quietest one PayPal offers: a single 32px row, no stacked card button, no
 * tagline, in the PayPal colour closest to the rail (black on the dark theme,
 * silver on the light one). Appearance only; the subscription flow is unchanged.
 */
export function crewButtonStyle(theme: ShellTheme) {
  return {
    label: "subscribe",
    layout: "horizontal",
    tagline: false,
    height: 32,
    shape: "rect",
    color: theme === "light" ? "silver" : "black",
  } as const;
}

function readShellTheme(): ShellTheme {
  return document.documentElement.dataset.theme === "light" ? "light" : "dark";
}

/** The theme lives on <html data-theme>; follow it so the button is redrawn on a switch. */
export function useShellTheme(): ShellTheme {
  const [theme, setTheme] = useState<ShellTheme>(readShellTheme);
  useEffect(() => {
    if (typeof MutationObserver === "undefined") return undefined;
    const observer = new MutationObserver(() => setTheme(readShellTheme()));
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => observer.disconnect();
  }, []);
  return theme;
}

type PlanLoadIssue = "missing" | "timeout" | null;

export function useCrewSupporterPlanId(planIdProp?: string) {
  const { t, i18n } = useTranslation();
  const appLang = String(i18n.language || "fr").startsWith("en") ? "en" : "fr";
  const [planId, setPlanId] = useState(() => (planIdProp || "").trim());
  const [planLoading, setPlanLoading] = useState(false);
  const [planLoadIssue, setPlanLoadIssue] = useState<PlanLoadIssue>(null);
  const [fetchError, setFetchError] = useState<string | null>(null);

  useEffect(() => {
    const forced = (planIdProp || "").trim();
    if (forced) {
      setPlanId(forced);
      setPlanLoading(false);
      setPlanLoadIssue(null);
      setFetchError(null);
      return;
    }
    let cancelled = false;
    setPlanId("");
    setPlanLoading(true);
    setPlanLoadIssue(null);
    setFetchError(null);
    const timeoutId = window.setTimeout(() => {
      if (!cancelled) {
        setPlanLoading(false);
        setPlanLoadIssue("timeout");
      }
    }, PLAN_LOAD_TIMEOUT_MS);
    void fetchCrewSupporterPlan(appLang)
      .then((body) => {
        if (cancelled) return;
        const id = String(body.plan_id || "").trim();
        if (id) {
          setPlanId(id);
        } else {
          setPlanLoadIssue("missing");
        }
      })
      .catch((e) => {
        if (!cancelled) setFetchError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) {
          setPlanLoading(false);
          window.clearTimeout(timeoutId);
        }
      });
    return () => {
      cancelled = true;
      window.clearTimeout(timeoutId);
    };
  }, [planIdProp, appLang]);

  return {
    t,
    appLang,
    planId,
    planLoading,
    planLoadIssue,
    fetchError,
    timeoutMessage: t("pledge.crewSubscribePlanTimeout"),
  };
}

export function CrewSupporterPublicSection({ adminKey }: { adminKey?: string }) {
  const { t } = useTranslation();
  const treasurerContext = Boolean(adminKey?.trim());
  const { planId, planLoading, planLoadIssue, fetchError, timeoutMessage } = useCrewSupporterPlanId();

  if (!treasurerContext && !planId) {
    return null;
  }

  const showTreasurerHint =
    treasurerContext && !planId && !planLoading && (planLoadIssue === "missing" || planLoadIssue === "timeout");

  return (
    <section className="crew-supporter-public" data-testid="crew-supporter-public">
      <div className="crew-supporter-heading">
        <h2>{t("pledge.crewSubscribeHint")}</h2>
        <small className="crew-sandbox-note">{t("pledge.crewSubscribeSandbox")}</small>
      </div>
      <div className="crew-paypal-frame">
        {showTreasurerHint ? (
          <div className="crew-subscribe" data-testid="crew-subscribe">
            <p className="hint" data-testid="crew-subscribe-treasurer-hint">
              {t("pledge.crewSubscribePlanTreasurerHint")}
            </p>
            {planLoadIssue === "timeout" ? <p className="hint">{timeoutMessage}</p> : null}
          </div>
        ) : treasurerContext && planLoading && !planId ? (
          <div className="crew-subscribe" data-testid="crew-subscribe">
            <p className="status">{t("pledge.crewSubscribeLoading")}</p>
          </div>
        ) : fetchError && treasurerContext && !planId ? (
          <div className="crew-subscribe" data-testid="crew-subscribe">
            <p className="hint" data-testid="crew-subscribe-treasurer-hint">
              {t("pledge.crewSubscribePlanTreasurerHint")}
            </p>
            <p className="hint">{fetchError}</p>
          </div>
        ) : planId ? (
          <CrewSubscribeButton
            adminKey={adminKey}
            planId={planId}
            treasurerContext={treasurerContext}
            suppressHeadingHint
          />
        ) : null}
      </div>
    </section>
  );
}

/**
 * Picks the subscription button for this page load. `CrewSubscribeButtonInner` below is
 * today's JS SDK v5 button and stays the default; `CrewSubscribeButtonV6Inner` is used only
 * when the backend reports `features.paypal_js_v6` (see paypal/paypalJsVersion.ts).
 */
export function CrewSubscribeButton(props: CrewSubscribeButtonProps) {
  const version = usePayPalJsVersion();
  if (version === null) return null;
  return (
    <PayPalErrorBoundary testId="crew-subscribe-error">
      {version === "v6" ? <CrewSubscribeButtonV6Inner {...props} /> : <CrewSubscribeButtonInner {...props} />}
    </PayPalErrorBoundary>
  );
}

function CrewSubscribeButtonInner({
  planId: planIdProp,
  adminKey,
  treasurerContext = Boolean(adminKey?.trim()),
  suppressHeadingHint = false,
}: CrewSubscribeButtonProps) {
  const { t, appLang, planId, planLoading, planLoadIssue, fetchError, timeoutMessage } =
    useCrewSupporterPlanId(planIdProp);
  const host = useRef<HTMLDivElement | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [paypal, setPaypal] = useState<PayPalNamespace | null>(null);
  const ready = paypal !== null;
  const [status, setStatus] = useState<string | null>(null);
  const theme = useShellTheme();

  useEffect(() => {
    return subscribeCrewSubscribeReturn(() => {
      setStatus(null);
      setError(null);
    });
  }, []);

  useEffect(() => {
    const clientId = String(import.meta.env.VITE_PAYPAL_CLIENT_ID ?? "").trim();
    if (!clientId || !planId.trim()) return;
    let cancelled = false;
    setPaypal(null);
    setError(null);
    void loadPayPalSubscriptionSdk(clientId, appLang)
      .then((ns) => {
        if (!cancelled) setPaypal(ns);
      })
      .catch((e) => {
        if (!cancelled) {
          setPaypal(null);
          setError(e instanceof Error ? e.message : String(e));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [planId, appLang]);

  useEffect(() => {
    if (!paypal || !planId.trim()) return;
    let closed = false;
    let buttons: PayPalSdkButtonInstance | null = null;
    const timer = window.setTimeout(() => {
      const container = host.current;
      if (closed || !container) return;
      container.replaceChildren();
      void safePayPalRender(
        paypal.Buttons,
        {
          style: crewButtonStyle(theme),
          createSubscription: (
            _data: unknown,
            actions: { subscription: { create: (body: unknown) => Promise<string> } },
          ) => actions.subscription.create({ plan_id: planId }),
          onApprove: (data: { subscriptionID?: string }) => {
            const subId = data.subscriptionID;
            if (!subId) return;
            void approveCrewSubscription({ subscription_id: subId, plan_id: planId })
              .then(() => {
                setStatus(t("pledge.crewSubscribeSaved"));
              })
              .catch((e) => {
                setError(e instanceof Error ? e.message : String(e));
              });
            if (adminKey?.trim()) {
              void recordSubscription(adminKey.trim(), {
                subscription_id: subId,
                plan_id: planId,
                status: "ACTIVE",
              }).catch(() => {
                /* webhook or public approve already recorded */
              });
            }
          },
        },
        container,
      ).then((result) => {
        buttons = result.instance;
        if (closed) {
          safePayPalClose(buttons);
          return;
        }
        if (!result.ok && result.error) {
          const e = result.error;
          setError(e instanceof Error ? e.message : String(e));
        }
      });
    }, 0);
    return () => {
      closed = true;
      window.clearTimeout(timer);
      safePayPalClose(buttons);
      host.current?.replaceChildren();
    };
  }, [paypal, planId, adminKey, appLang, t, theme]);

  if (!treasurerContext && !planId && (planLoading || planLoadIssue || fetchError)) {
    return null;
  }

  if (!planId && !treasurerContext) {
    return null;
  }

  if (treasurerContext && !planId && !planLoading && planLoadIssue === "missing") {
    return (
      <div className="crew-subscribe" data-testid="crew-subscribe">
        <p className="hint" data-testid="crew-subscribe-treasurer-hint">
          {t("pledge.crewSubscribePlanTreasurerHint")}
        </p>
      </div>
    );
  }

  if (treasurerContext && !planId && !planLoading && planLoadIssue === "timeout") {
    return (
      <div className="crew-subscribe" data-testid="crew-subscribe">
        <p className="hint" data-testid="crew-subscribe-treasurer-hint">
          {t("pledge.crewSubscribePlanTreasurerHint")}
        </p>
        <p className="hint">{timeoutMessage}</p>
      </div>
    );
  }

  if (!planId && !planLoadIssue && !fetchError && planLoading) {
    return (
      <div className="crew-subscribe" data-testid="crew-subscribe">
        {suppressHeadingHint ? null : <p className="hint">{t("pledge.crewSubscribeHint")}</p>}
        <p className="status">{t("pledge.crewSubscribeLoading")}</p>
      </div>
    );
  }

  return (
    <div className="crew-subscribe" data-testid="crew-subscribe">
      {suppressHeadingHint ? null : <p className="hint">{t("pledge.crewSubscribeHint")}</p>}
      {!ready && !error && planId ? (
        <p className="status" data-testid="crew-subscribe-loading">
          {t("pledge.crewSubscribeLoading")}
        </p>
      ) : null}
      <div ref={host} data-testid="crew-subscribe-host" />
      {status ? <p className="status">{status}</p> : null}
      {error ? <p className="notice error">{error}</p> : null}
    </div>
  );
}

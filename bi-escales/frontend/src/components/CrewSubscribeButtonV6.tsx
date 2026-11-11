/**
 * Crew subscription button on PayPal Web SDK v6. Rendered instead of the v5 inner
 * component only when the backend reports `features.paypal_js_v6` (see
 * CrewSubscribeButton.tsx and paypal/paypalJsVersion.ts). A copy of the v5
 * component with the same markup, test ids and copy, and these differences:
 *
 *  - the SDK is the v6 adapter: a subscription payment session, the plan shown
 *    to the payer sent as a constraint and checked against the plan the server
 *    actually created;
 *  - "saved" is shown only after the server has verified the subscription is
 *    ACTIVE on the plan that was displayed; the approval callback waits for it.
 */
import { useEffect, useRef, useState } from "react";
import { approveCrewSubscription, recordSubscription } from "../api/escales";
import {
  loadPayPalSubscriptionSdk,
  safePayPalClose,
  safePayPalRender,
  type PayPalNamespace,
  type PayPalSdkButtonInstance,
} from "../paypal/v6/paypalSdkV6";
import { subscribeCrewSubscribeReturn } from "../paypal/crewSubscribeReturnEvents";
import {
  crewButtonStyle,
  useCrewSupporterPlanId,
  useShellTheme,
  type CrewSubscribeButtonProps,
} from "./CrewSubscribeButton";

const activeReceipts = new Map<string, Promise<Record<string, unknown>>>();

/** One server verification per subscription and plan, shared by every caller; a failure can be retried. */
function verifyActiveSubscription(subscription_id: string, plan_id: string) {
  const key = `${subscription_id}:${plan_id}`;
  let pending = activeReceipts.get(key);
  if (!pending) {
    pending = approveCrewSubscription({ subscription_id, plan_id })
      .then((receipt) => {
        if (receipt.status !== "ACTIVE" || receipt.plan_id !== plan_id) {
          throw new Error("Subscription activation has not been verified");
        }
        return receipt;
      })
      .catch((error) => {
        activeReceipts.delete(key);
        throw error;
      });
    activeReceipts.set(key, pending);
  }
  return pending;
}

export function CrewSubscribeButtonV6Inner({
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
          subscriptionPlanId: planId,
          createSubscription: (
            _data: unknown,
            actions: { subscription: { create: (body: unknown) => Promise<string> } },
          ) => actions.subscription.create({ plan_id: planId }),
          onApprove: async (data: { subscriptionID?: string }) => {
            const subId = data.subscriptionID;
            if (!subId) throw new Error("Subscription ID missing");
            try {
              await verifyActiveSubscription(subId, planId);
              if (!closed) setStatus(t("pledge.crewSubscribeSaved"));
            } catch (e) {
              if (!closed) setError(e instanceof Error ? e.message : "Subscription verification failed");
              throw e;
            }
            if (adminKey?.trim()) {
              void recordSubscription(adminKey.trim(), {
                subscription_id: subId,
                plan_id: planId,
                status: "ACTIVE",
              }).catch(() => {
                /* the verified server receipt remains authoritative */
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
    <div className="crew-subscribe" data-testid="crew-subscribe" data-paypal-js="v6">
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

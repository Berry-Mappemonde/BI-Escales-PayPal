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

export interface CrewSubscribeButtonProps {
  planId?: string;
  adminKey?: string;
}

const PLAN_LOAD_TIMEOUT_MS = 20_000;

export function CrewSubscribeButton(props: CrewSubscribeButtonProps) {
  return (
    <PayPalErrorBoundary testId="crew-subscribe-error">
      <CrewSubscribeButtonInner {...props} />
    </PayPalErrorBoundary>
  );
}

function CrewSubscribeButtonInner({ planId: planIdProp, adminKey }: CrewSubscribeButtonProps) {
  const { t, i18n } = useTranslation();
  const appLang = String(i18n.language || "fr").startsWith("en") ? "en" : "fr";
  const host = useRef<HTMLDivElement | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [paypal, setPaypal] = useState<PayPalNamespace | null>(null);
  const ready = paypal !== null;
  const [planId, setPlanId] = useState(() => (planIdProp || "").trim());
  const [status, setStatus] = useState<string | null>(null);
  const [planLoading, setPlanLoading] = useState(false);

  useEffect(() => {
    setPlanId((planIdProp || "").trim());
  }, [planIdProp]);

  useEffect(() => {
    if (planId) return;
    let cancelled = false;
    setPlanLoading(true);
    setError(null);
    const timeoutId = window.setTimeout(() => {
      if (!cancelled) {
        setPlanLoading(false);
        setError(t("pledge.crewSubscribePlanTimeout"));
      }
    }, PLAN_LOAD_TIMEOUT_MS);
    void fetchCrewSupporterPlan(appLang)
      .then((body) => {
        if (cancelled) return;
        const id = String(body.plan_id || "").trim();
        if (id) {
          setPlanId(id);
        } else {
          setError(t("pledge.crewSubscribePlanMissing"));
        }
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
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
  }, [planId, t, appLang]);

  useEffect(() => {
    return subscribeCrewSubscribeReturn(() => {
      setPlanLoading(false);
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
          style: { label: "subscribe", layout: "vertical" },
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
  }, [paypal, planId, adminKey, appLang, t]);

  if (!planId && !error && planLoading) {
    return (
      <div className="crew-subscribe" data-testid="crew-subscribe">
        <p className="hint">{t("pledge.crewSubscribeHint")}</p>
        <p className="status">{t("pledge.crewSubscribeLoading")}</p>
      </div>
    );
  }

  return (
    <div className="crew-subscribe" data-testid="crew-subscribe">
      <p className="hint">{t("pledge.crewSubscribeHint")}</p>
      {!ready && !error ? (
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

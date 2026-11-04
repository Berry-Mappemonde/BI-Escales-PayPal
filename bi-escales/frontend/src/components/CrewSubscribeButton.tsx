import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { approveCrewSubscription, fetchCrewSupporterPlan, recordSubscription } from "../api/escales";
import { loadPayPalSubscriptionSdk } from "../paypal/paypalSdk";
import { subscribeCrewSubscribeReturn } from "../paypal/crewSubscribeReturnEvents";

export interface CrewSubscribeButtonProps {
  planId?: string;
  adminKey?: string;
}

const PLAN_LOAD_TIMEOUT_MS = 20_000;

export function CrewSubscribeButton({ planId: planIdProp, adminKey }: CrewSubscribeButtonProps) {
  const { t, i18n } = useTranslation();
  const host = useRef<HTMLDivElement | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
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
    void fetchCrewSupporterPlan()
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
  }, [planId, t]);

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
    void loadPayPalSubscriptionSdk(clientId)
      .then(() => {
        if (!cancelled) setReady(true);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [planId]);

  useEffect(() => {
    if (!ready || !host.current || !window.paypal?.Buttons || !planId.trim()) return;
    const container = host.current;
    container.replaceChildren();
    const buttons = window.paypal.Buttons({
      style: { label: "subscribe", layout: "vertical" },
      createSubscription: (_data: unknown, actions: { subscription: { create: (body: unknown) => Promise<string> } }) =>
        actions.subscription.create({ plan_id: planId }),
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
    });
    void buttons.render(container);
    return () => {
      void buttons.close();
      container.replaceChildren();
    };
  }, [ready, planId, adminKey, i18n.language, t]);

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
      <div ref={host} data-testid="crew-subscribe-host" />
      {status ? <p className="status">{status}</p> : null}
      {error ? <p className="notice error">{error}</p> : null}
    </div>
  );
}

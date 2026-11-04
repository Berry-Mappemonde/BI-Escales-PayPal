import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { loadPayPalSubscriptionSdk } from "../paypal/paypalSdk";
import { recordSubscription } from "../api/escales";

export interface CrewSubscribeButtonProps {
  planId: string;
  adminKey?: string;
}

export function CrewSubscribeButton({ planId, adminKey }: CrewSubscribeButtonProps) {
  const { t } = useTranslation();
  const host = useRef<HTMLDivElement | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

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
    const buttons = window.paypal.Buttons({
      style: { label: "subscribe", layout: "vertical" },
      createSubscription: (_data: unknown, actions: { subscription: { create: (body: unknown) => Promise<string> } }) =>
        actions.subscription.create({ plan_id: planId }),
      onApprove: (data: { subscriptionID?: string }) => {
        const subId = data.subscriptionID;
        if (subId && adminKey?.trim()) {
          void recordSubscription(adminKey.trim(), {
            subscription_id: subId,
            plan_id: planId,
            status: "ACTIVE",
          }).catch(() => {
            /* treasurer may record via webhook */
          });
        }
      },
    });
    void buttons.render(host.current);
  }, [ready, planId, adminKey]);

  return (
    <div className="crew-subscribe" data-testid="crew-subscribe">
      <p className="hint">{t("pledge.crewSubscribeHint")}</p>
      <div ref={host} data-testid="crew-subscribe-host" />
      {error ? <p className="notice error">{error}</p> : null}
    </div>
  );
}

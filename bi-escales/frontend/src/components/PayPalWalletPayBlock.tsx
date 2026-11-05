import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { authorizePledge, createPledge } from "../api/escales";
import type { PledgeFormValues } from "./PledgeButton";

export interface PayPalWalletPayBlockProps {
  values: PledgeFormValues;
  appLang: string;
  sdkIntent: "authorize" | "capture";
  disabled?: boolean;
  onAuthorized?: (pledge: import("../api/types").PublicPledge) => void;
}

/** Google Pay + Apple Pay (TEST sandbox, components=googlepay,applepay). */
export function PayPalWalletPayBlock({
  values,
  appLang,
  sdkIntent,
  disabled,
  onAuthorized,
}: PayPalWalletPayBlockProps) {
  const { t } = useTranslation();
  const googleHost = useRef<HTMLDivElement | null>(null);
  const appleHost = useRef<HTMLDivElement | null>(null);
  const valuesRef = useRef(values);
  valuesRef.current = values;

  useEffect(() => {
    if (disabled) return;
    const googleEl = googleHost.current;
    const appleEl = appleHost.current;
    if (!googleEl && !appleEl) return;

    const makeOrder = async () => {
      const v = valuesRef.current;
      const pledge = await createPledge(
        {
          amount_eur: v.amount_eur,
          description: v.description,
          milestone_id: v.milestone_id,
          contributor: v.contributor?.trim() || undefined,
          kind: v.kind,
          target_id: v.target_id,
          lang: v.lang || appLang,
        },
        crypto.randomUUID(),
      );
      if (!pledge.order_id) throw new Error("order_id missing");
      return { orderId: pledge.order_id, pledgeId: pledge.id };
    };

    const onApprove = async (pledgeId: string) => {
      const done = await authorizePledge(pledgeId);
      onAuthorized?.(done);
    };

    const Googlepay = window.paypal?.Googlepay;
    const Applepay = window.paypal?.Applepay;
    let googleButtons: { close?: () => Promise<void> } | null = null;
    let appleButtons: { close?: () => Promise<void> } | null = null;

    if (Googlepay && googleEl) {
      googleEl.innerHTML = "";
      let pledgeId: string | null = null;
      const gp = Googlepay({
        createOrder: async () => {
          const row = await makeOrder();
          pledgeId = row.pledgeId;
          return row.orderId;
        },
        onApprove: async () => {
          if (pledgeId) await onApprove(pledgeId);
        },
      });
      void gp.render(googleEl).catch(() => undefined);
      googleButtons = gp;
      googleEl.dataset.googlePay = "1";
    }

    if (Applepay && appleEl) {
      appleEl.innerHTML = "";
      let pledgeId: string | null = null;
      const ap = Applepay({
        createOrder: async () => {
          const row = await makeOrder();
          pledgeId = row.pledgeId;
          return row.orderId;
        },
        onApprove: async () => {
          if (pledgeId) await onApprove(pledgeId);
        },
      });
      void ap.render(appleEl).catch(() => undefined);
      appleButtons = ap;
      appleEl.dataset.applePay = "1";
    }

    return () => {
      void googleButtons?.close?.().catch(() => undefined);
      void appleButtons?.close?.().catch(() => undefined);
    };
  }, [appLang, disabled, sdkIntent, onAuthorized, values.amount_eur, values.kind, values.milestone_id]);

  return (
    <div className="paypal-wallet-pay" data-testid="paypal-wallet-pay">
      <p className="hint">{t("pledge.walletPayHint")}</p>
      <div ref={googleHost} data-testid="paypal-google-pay" />
      <div ref={appleHost} data-testid="paypal-apple-pay" />
    </div>
  );
}

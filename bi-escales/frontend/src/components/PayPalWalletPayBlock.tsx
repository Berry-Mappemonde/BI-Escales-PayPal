import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { authorizePledge, createPledge } from "../api/escales";
import {
  safePayPalClose,
  safePayPalRender,
  type PayPalNamespace,
  type PayPalSdkButtonInstance,
} from "../paypal/paypalSdk";
import type { PledgeFormValues } from "./PledgeButton";

export interface PayPalWalletPayBlockProps {
  values: PledgeFormValues;
  appLang: string;
  sdkIntent: "authorize" | "capture";
  /** Parent finished loading the PayPal SDK (with applepay/googlepay when wallet_pay is on). */
  sdkReady?: boolean;
  /** Namespaced SDK object loaded by the parent (never `window.paypal`). */
  paypal?: PayPalNamespace | null;
  disabled?: boolean;
  onAuthorized?: (pledge: import("../api/types").PublicPledge) => void;
}

/** Google Pay + Apple Pay (TEST sandbox, components=googlepay,applepay). */
export function PayPalWalletPayBlock({
  values,
  appLang,
  sdkIntent,
  sdkReady = false,
  paypal = null,
  disabled,
  onAuthorized,
}: PayPalWalletPayBlockProps) {
  const { t } = useTranslation();
  const googleHost = useRef<HTMLDivElement | null>(null);
  const appleHost = useRef<HTMLDivElement | null>(null);
  const valuesRef = useRef(values);
  valuesRef.current = values;

  useEffect(() => {
    if (disabled || !sdkReady) return;
    const googleEl = googleHost.current;
    const appleEl = appleHost.current;
    if (!googleEl && !appleEl) return;
    // Eligibility: Googlepay/Applepay may be absent (headless Chrome, non-Safari, no wallet).
    // Wait for sdkReady so we do not miss a late SDK load (race vs Smart Buttons).
    // PayPal SDK v5 Googlepay()/Applepay() return config helpers without `render`
    // (they need Google/Apple's own pay.js): safePayPalRender treats that as "not shown", never a crash.
    const Googlepay = paypal?.Googlepay;
    const Applepay = paypal?.Applepay;
    if (typeof Googlepay !== "function" && typeof Applepay !== "function") return;
    let closed = false;

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

    let googleButtons: PayPalSdkButtonInstance | null = null;
    let appleButtons: PayPalSdkButtonInstance | null = null;

    const mount = (factory: unknown, el: HTMLElement | null, flag: "googlePay" | "applePay") => {
      if (typeof factory !== "function" || !el) return;
      el.innerHTML = "";
      let pledgeId: string | null = null;
      void safePayPalRender(
        factory,
        {
          createOrder: async () => {
            const row = await makeOrder();
            pledgeId = row.pledgeId;
            return row.orderId;
          },
          onApprove: async () => {
            if (pledgeId) await onApprove(pledgeId);
          },
        },
        el,
      ).then((result) => {
        if (flag === "googlePay") googleButtons = result.instance;
        else appleButtons = result.instance;
        if (closed) safePayPalClose(result.instance);
        else if (result.ok) el.dataset[flag] = "1";
      });
    };

    mount(Googlepay, googleEl, "googlePay");
    mount(Applepay, appleEl, "applePay");

    return () => {
      closed = true;
      safePayPalClose(googleButtons);
      safePayPalClose(appleButtons);
    };
  }, [appLang, disabled, sdkReady, paypal, sdkIntent, onAuthorized, values.amount_eur, values.kind, values.milestone_id]);

  return (
    <div className="paypal-wallet-pay" data-testid="paypal-wallet-pay">
      <p className="hint">{t("pledge.walletPayHint")}</p>
      <div ref={googleHost} data-testid="paypal-google-pay" />
      <div ref={appleHost} data-testid="paypal-apple-pay" />
    </div>
  );
}

import { useEffect, useRef, useState } from "react";
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

/** Google Pay TEST and Apple Pay sandbox through PayPal Web SDK v6 sessions. */
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
  const [walletVisible, setWalletVisible] = useState(false);
  const [walletError, setWalletError] = useState(false);

  useEffect(() => {
    setWalletVisible(false);
    setWalletError(false);
    if (disabled || !sdkReady) return;
    const googleEl = googleHost.current;
    const appleEl = appleHost.current;
    if (!googleEl && !appleEl) return;
    // Wallet-specific merchant and device eligibility is evaluated independently
    // by the v6 adapter. An unavailable Apple wallet must not suppress Google Pay.
    const Googlepay = paypal?.Googlepay;
    const Applepay = paypal?.Applepay;
    if (typeof Googlepay !== "function" && typeof Applepay !== "function") return;
    let closed = false;
    setWalletVisible(false);

    const makeOrder = async () => {
      const v = valuesRef.current;
      const pledge = await createPledge(
        {
          amount_eur: v.amount_eur,
            quantity: v.quantity,
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
          amount: values.amount_eur,
          currencyCode: "EUR",
          createOrder: async () => {
            const row = await makeOrder();
            pledgeId = row.pledgeId;
            return row.orderId;
          },
          onError: () => { if (!closed) setWalletError(true); },
          onApprove: async () => {
            if (pledgeId) await onApprove(pledgeId);
          },
        },
        el,
      ).then((result) => {
        if (flag === "googlePay") googleButtons = result.instance;
        else appleButtons = result.instance;
        if (closed) safePayPalClose(result.instance);
        else if (result.ok) {
          el.dataset[flag] = "1";
          setWalletVisible(true);
        }
      });
    };

    mount(Googlepay, googleEl, "googlePay");
    mount(Applepay, appleEl, "applePay");

    return () => {
      closed = true;
      safePayPalClose(googleButtons);
      safePayPalClose(appleButtons);
    };
  }, [appLang, disabled, sdkReady, paypal, sdkIntent, onAuthorized, values.amount_eur, values.currency, values.quantity, values.kind, values.milestone_id]);

  return (
    <div className="paypal-wallet-pay" data-testid="paypal-wallet-pay">
      {walletVisible ? <p className="hint">{t("pledge.walletPayHint")}</p> : null}
      {walletError ? <p role="alert">{t("pledge.walletPayError")}</p> : null}
      <div ref={googleHost} data-testid="paypal-google-pay" />
      <div ref={appleHost} data-testid="paypal-apple-pay" />
    </div>
  );
}

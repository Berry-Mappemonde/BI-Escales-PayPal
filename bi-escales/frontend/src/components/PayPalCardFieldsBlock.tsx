import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { authorizePledge, createPledge, isVaultPledge, registerVault } from "../api/escales";
import type { PublicPledge } from "../api/types";
import type { PledgeFormValues } from "./PledgeButton";
import type { PayPalNamespace } from "../paypal/paypalSdk";

type CardFieldsFactory = (config: Record<string, unknown>) => {
  isEligible: () => boolean;
  NumberField: () => { render: (el: HTMLElement) => Promise<void> };
  ExpiryField: () => { render: (el: HTMLElement) => Promise<void> };
  CVVField: () => { render: (el: HTMLElement) => Promise<void> };
  submit: () => Promise<void>;
};

export interface PayPalCardFieldsBlockProps {
  values: PledgeFormValues;
  appLang: string;
  /** Namespaced SDK object loaded by PledgeButton (never `window.paypal`). */
  paypal?: PayPalNamespace | null;
  disabled?: boolean;
  onAuthorized?: (pledge: PublicPledge) => void;
}

/** In-page Card Fields (setup tokens + payment tokens for vault, card orders otherwise). */
export function PayPalCardFieldsBlock({
  values,
  appLang,
  paypal = null,
  disabled,
  onAuthorized,
}: PayPalCardFieldsBlockProps) {
  const { t } = useTranslation();
  const rootRef = useRef<HTMLDivElement | null>(null);
  const numberRef = useRef<HTMLDivElement | null>(null);
  const expiryRef = useRef<HTMLDivElement | null>(null);
  const cvvRef = useRef<HTMLDivElement | null>(null);
  const valuesRef = useRef(values);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const activePledgeRef = useRef<PublicPledge | null>(null);
  const submitRef = useRef<(() => Promise<void>) | null>(null);
  valuesRef.current = values;

  useEffect(() => {
    const CardFields = (paypal as { CardFields?: CardFieldsFactory } | null)?.CardFields;
    const numberHost = numberRef.current;
    const expiryHost = expiryRef.current;
    const cvvHost = cvvRef.current;
    if (typeof CardFields !== "function" || !numberHost || !expiryHost || !cvvHost || disabled) {
      setReady(false);
      return;
    }

    let cancelled = false;
    activePledgeRef.current = null;
    submitRef.current = null;

    const buildPledge = async () => {
      const v = valuesRef.current;
      return createPledge(
        {
          amount_eur: v.amount_eur,
          description: v.description,
          milestone_id: v.milestone_id,
          contributor: v.contributor?.trim() || undefined,
          kind: v.kind,
          target_id: v.target_id,
          lang: v.lang || appLang,
          checkout_method: "card",
        },
        crypto.randomUUID(),
      );
    };

    let cardFields: ReturnType<CardFieldsFactory>;
    try {
      cardFields = CardFields({
      createOrder: async () => {
        const pledge = await buildPledge();
        activePledgeRef.current = pledge;
        if (isVaultPledge(pledge)) {
          throw new Error("vault card uses setup token flow");
        }
        if (!pledge.order_id) throw new Error("order_id missing");
        return pledge.order_id;
      },
      createVaultSetupToken: async () => {
        const pledge = await buildPledge();
        activePledgeRef.current = pledge;
        const token = String(pledge.setup_token_id || "").trim();
        if (!token) throw new Error("setup_token_id missing");
        return token;
      },
    });
    } catch {
      setReady(false);
      return;
    }

    let eligible = false;
    try {
      eligible = typeof cardFields?.isEligible === "function" && cardFields.isEligible();
    } catch {
      eligible = false;
    }
    if (!eligible) {
      if (!cancelled) setReady(false);
      return;
    }

    void (async () => {
      try {
        for (const [field, el] of [
          [cardFields.NumberField, numberHost],
          [cardFields.ExpiryField, expiryHost],
          [cardFields.CVVField, cvvHost],
        ] as const) {
          if (typeof field !== "function") throw new Error("PayPal card field unavailable");
          const instance = field.call(cardFields);
          if (typeof instance?.render !== "function") throw new Error("PayPal card field cannot render");
          await instance.render(el);
        }
        if (!cancelled) {
          submitRef.current = () => cardFields.submit();
          setReady(true);
        }
      } catch {
        if (!cancelled) setReady(false);
      }
    })();

    return () => {
      cancelled = true;
      setReady(false);
      submitRef.current = null;
    };
  }, [appLang, paypal, disabled, values.amount_eur, values.kind, values.milestone_id, values.description, values.target_id]);

  const onSubmit = async () => {
    const submit = submitRef.current;
    const pledge = activePledgeRef.current;
    if (!submit) return;
    setBusy(true);
    setError(null);
    try {
      await submit();
      let current = pledge;
      if (!current) {
        throw new Error("pledge missing after card submit");
      }
      if (isVaultPledge(current)) {
        current = await registerVault(current.id, current.setup_token_id || undefined);
      } else {
        current = await authorizePledge(current.id);
      }
      onAuthorized?.(current);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="paypal-card-fields" data-testid="paypal-card-fields" ref={rootRef}>
      <p className="hint">{t("pledge.cardFieldsHint")}</p>
      <div className="card-field-row">
        <div ref={numberRef} data-testid="paypal-card-number" />
        <div ref={expiryRef} data-testid="paypal-card-expiry" />
        <div ref={cvvRef} data-testid="paypal-card-cvv" />
      </div>
      <button type="button" data-testid="paypal-card-submit" disabled={!ready || busy || disabled} onClick={() => void onSubmit()}>
        {t("pledge.cardPay")}
      </button>
      {error ? (
        <p className="notice error">
          {t("pledge.error")}: {error}
        </p>
      ) : null}
    </div>
  );
}

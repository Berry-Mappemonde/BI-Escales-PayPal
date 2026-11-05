import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { authorizePledge, createPledge, fetchPledgeMode, isVaultPledge, registerVault } from "../api/escales";
import type { PublicPledge } from "../api/types";
import type { PledgeFormValues } from "./PledgeButton";
import type { PayPalNamespace } from "../paypal/paypalSdk";

type FieldInstance = { render: (el: HTMLElement) => Promise<void>; close?: () => void | Promise<void> };

type CardFieldsFactory = (config: Record<string, unknown>) => {
  isEligible: () => boolean;
  NumberField: () => FieldInstance;
  ExpiryField: () => FieldInstance;
  CVVField: () => FieldInstance;
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
  const attemptRef = useRef<{ key: string; values: PledgeFormValues; pledge?: Promise<PublicPledge> } | null>(null);
  const submittingRef = useRef(false);
  valuesRef.current = values;

  useEffect(() => {
    setReady(false);
    setError(null);
    submitRef.current = null;
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
      if (cancelled || !submittingRef.current || !attemptRef.current) throw new Error("Press Pay to start card checkout");
      const attempt = attemptRef.current;
      if (!attempt.pledge) {
        const v = attempt.values;
        attempt.pledge = createPledge({
          ...v,
          contributor: v.contributor?.trim() || undefined,
          lang: v.lang || appLang,
          checkout_method: "card",
        }, attempt.key);
      }
      const pledge = await attempt.pledge;
      if (cancelled) throw new Error("Card checkout closed");
      activePledgeRef.current = pledge;
      return pledge;
    };

    const instances: FieldInstance[] = [];
    const dispose = () => {
      for (const instance of instances.splice(0)) {
        try { void Promise.resolve(instance.close?.()).catch(() => undefined); } catch { /* already closed */ }
      }
    };
    void (async () => {
      try {
        const { payment_mode } = await fetchPledgeMode(values.milestone_id, values.kind);
        if (cancelled) return;
        const callbacks = payment_mode === "VAULT"
          ? { createVaultSetupToken: async () => {
              const pledge = await buildPledge();
              if (!isVaultPledge(pledge) || !pledge.setup_token_id) throw new Error("Payment mode changed; reopen checkout");
              return pledge.setup_token_id;
            } }
          : { createOrder: async () => {
              const pledge = await buildPledge();
              if (isVaultPledge(pledge) || !pledge.order_id) throw new Error("Payment mode changed; reopen checkout");
              return pledge.order_id;
            } };
        const cardFields = CardFields(callbacks);
        if (!cardFields.isEligible()) return;
        for (const [field, el] of [
          [cardFields.NumberField, numberHost],
          [cardFields.ExpiryField, expiryHost],
          [cardFields.CVVField, cvvHost],
        ] as const) {
          if (cancelled) return;
          const instance = field.call(cardFields);
          instances.push(instance);
          await instance.render(el);
          if (cancelled) return;
        }
        submitRef.current = () => cardFields.submit();
        setReady(true);
      } catch (e) {
        dispose();
        if (!cancelled) {
          setReady(false);
          setError(e instanceof Error ? e.message : String(e));
        }
      }
    })();

    return () => {
      cancelled = true;
      submitRef.current = null;
      activePledgeRef.current = null;
      attemptRef.current = null;
      dispose();
    };
  }, [appLang, paypal, disabled, values.kind, values.milestone_id]);

  const onSubmit = async () => {
    const submit = submitRef.current;
    if (!submit || submittingRef.current) return;
    submittingRef.current = true;
    const snapshot = { ...valuesRef.current };
    // Keep a failed attempt's key for a retry of identical values.
    if (!attemptRef.current || JSON.stringify(attemptRef.current.values) !== JSON.stringify(snapshot)) {
      attemptRef.current = { key: crypto.randomUUID(), values: snapshot };
    } else if (attemptRef.current.pledge) {
      // Reuse the same server idempotency key after a transport failure.
      attemptRef.current.pledge = undefined;
    }
    setBusy(true);
    setError(null);
    try {
      await submit();
      let current = activePledgeRef.current;
      if (!current) {
        throw new Error("pledge missing after card submit");
      }
      if (isVaultPledge(current)) {
        current = await registerVault(current.id, current.setup_token_id || undefined);
      } else {
        current = await authorizePledge(current.id);
      }
      attemptRef.current = null;
      setReady(false);
      onAuthorized?.(current);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      submittingRef.current = false;
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

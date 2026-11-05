import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { authorizePledge, createPledge, isVaultPledge, registerVault } from "../api/escales";
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
  const preparedRef = useRef<{ key: string; pledge: Promise<PublicPledge> } | null>(null);
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

    const instances: FieldInstance[] = [];
    const dispose = () => {
      for (const instance of instances.splice(0)) {
        try { void Promise.resolve(instance.close?.()).catch(() => undefined); } catch { /* already closed */ }
      }
    };
    // The server chooses AUTHORIZE/VAULT using its clock and feature flags.
    // Prepare a draft (no charge) before selecting the mutually exclusive SDK callback.
    const key = JSON.stringify([values, appLang]);
    if (preparedRef.current?.key !== key) {
      preparedRef.current = { key, pledge: buildPledge() };
    }
    const prepared = preparedRef.current;
    void (async () => {
      try {
        const pledge = await prepared.pledge;
        if (cancelled) return;
        const activate = () => {
          if (cancelled) throw new Error("Card checkout closed");
          activePledgeRef.current = pledge;
        };
        const callbacks = isVaultPledge(pledge)
          ? { createVaultSetupToken: async () => {
              activate();
              if (!pledge.setup_token_id) throw new Error("setup_token_id missing");
              return pledge.setup_token_id;
            } }
          : { createOrder: async () => {
              activate();
              if (!pledge.order_id) throw new Error("order_id missing");
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
        if (preparedRef.current === prepared) preparedRef.current = null;
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
      dispose();
    };
  }, [appLang, paypal, disabled, values.amount_eur, values.kind, values.milestone_id, values.description, values.target_id]);

  const onSubmit = async () => {
    const submit = submitRef.current;
    if (!submit) return;
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
      preparedRef.current = null;
      setReady(false);
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

import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
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

const CARD_ERROR_I18N: Record<string, string> = {
  INVALID_EXPIRY: "pledge.cardErrorInvalidExpiry",
  INVALID_CVV: "pledge.cardErrorInvalidCvv",
  INVALID_NUMBER: "pledge.cardErrorInvalidNumber",
};

export function formatCardFieldError(message: string, t: TFunction): string {
  const trimmed = message.trim();
  const upper = trimmed.toUpperCase();
  const direct = CARD_ERROR_I18N[upper];
  if (direct) return t(direct);
  for (const [code, key] of Object.entries(CARD_ERROR_I18N)) {
    if (upper.includes(code)) return t(key);
  }
  return trimmed;
}

function isCabinLegKind(kind?: string): boolean {
  return (kind || "") === "cabin_leg";
}

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
  const [confirmed, setConfirmed] = useState<PublicPledge | null>(null);
  const activePledgeRef = useRef<PublicPledge | null>(null);
  const submitRef = useRef<(() => Promise<void>) | null>(null);
  const attemptRef = useRef<{ key: string; values: PledgeFormValues; pledge?: Promise<PublicPledge> } | null>(null);
  const submittingRef = useRef(false);
  const generationRef = useRef(0);
  const pledgeTargetRef = useRef(`${values.milestone_id}\0${values.kind ?? ""}`);
  valuesRef.current = values;

  useEffect(() => {
    const target = `${values.milestone_id}\0${values.kind ?? ""}`;
    if (pledgeTargetRef.current !== target) {
      pledgeTargetRef.current = target;
      setConfirmed(null);
    }
  }, [values.kind, values.milestone_id]);

  useEffect(() => {
    if (confirmed) return;

    generationRef.current += 1;
    submittingRef.current = false;
    setReady(false);
    setBusy(false);
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
        // The SDK calls onApprove/onError after confirm-payment-source; without them
        // submit() rejects ("p is not a function") and authorize is never reached.
        // Authorization/vault registration stays in onSubmit after submit() resolves.
        const cardFields = CardFields({
          ...callbacks,
          onApprove: () => undefined,
          onError: () => undefined,
        });
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
          setError(formatCardFieldError(e instanceof Error ? e.message : String(e), t));
        }
      }
    })();

    return () => {
      cancelled = true;
      generationRef.current += 1;
      submitRef.current = null;
      activePledgeRef.current = null;
      attemptRef.current = null;
      dispose();
    };
  }, [appLang, paypal, disabled, values.kind, values.milestone_id, confirmed, t]);

  const onSubmit = async () => {
    const submit = submitRef.current;
    if (!submit || submittingRef.current) return;
    const generation = generationRef.current;
    const isClosed = () => generation !== generationRef.current;
    submittingRef.current = true;
    const snapshot = { ...valuesRef.current };
    // Keep a failed attempt's key for a retry of identical values.
    if (!attemptRef.current || JSON.stringify(attemptRef.current.values) !== JSON.stringify(snapshot)) {
      attemptRef.current = { key: crypto.randomUUID(), values: snapshot };
      activePledgeRef.current = null;
    } else if (!activePledgeRef.current) {
      // Reuse the same server idempotency key after a transport failure.
      attemptRef.current.pledge = undefined;
    }
    setBusy(true);
    setError(null);
    try {
      await submit();
      if (isClosed()) return;
      let current = activePledgeRef.current;
      if (!current) {
        throw new Error("pledge missing after card submit");
      }
      if (isVaultPledge(current)) {
        current = await registerVault(current.id, current.setup_token_id || undefined);
      } else {
        current = await authorizePledge(current.id);
      }
      if (isClosed()) return;
      attemptRef.current = null;
      setReady(false);
      setConfirmed(current);
      onAuthorized?.(current);
    } catch (e) {
      if (!isClosed()) setError(formatCardFieldError(e instanceof Error ? e.message : String(e), t));
    } finally {
      if (!isClosed()) {
        submittingRef.current = false;
        setBusy(false);
      }
    }
  };

  const shortRef = confirmed ? confirmed.id.slice(0, 8) : "";
  const vaultConfirmed = confirmed ? isVaultPledge(confirmed) : false;
  const confirmKind = confirmed?.kind ?? values.kind;

  return (
    <div className="paypal-card-fields" data-testid="paypal-card-fields" ref={rootRef}>
      {confirmed ? (
        <div data-testid="paypal-card-confirm">
          <p className="status">
            {t(vaultConfirmed ? "pledge.cardConfirmVaultTitle" : "pledge.cardConfirmAuthorizeTitle")}
          </p>
          <p className="hint" data-testid="paypal-card-confirm-ref">
            {t("pledge.cardConfirmRef", { ref: shortRef })}
          </p>
          <p className="hint" data-testid="paypal-card-confirm-next">
            {t(isCabinLegKind(confirmKind) ? "pledge.cardConfirmCabinNext" : "pledge.cardConfirmStopNext")}
          </p>
        </div>
      ) : null}
      <div data-testid="paypal-card-checkout" hidden={Boolean(confirmed)}>
        <p className="hint">{t("pledge.cardFieldsHint")}</p>
        <div className="card-field-row">
          <div ref={numberRef} data-testid="paypal-card-number" />
          <div ref={expiryRef} data-testid="paypal-card-expiry" />
          <div ref={cvvRef} data-testid="paypal-card-cvv" />
        </div>
        <button
          type="button"
          data-testid="paypal-card-submit"
          disabled={!ready || busy || disabled}
          onClick={() => void onSubmit()}
        >
          {busy ? t("pledge.authorizing") : t("pledge.cardPay")}
        </button>
      </div>
      {error ? (
        <p className="notice error">
          {t("pledge.error")}: {error}
        </p>
      ) : null}
    </div>
  );
}

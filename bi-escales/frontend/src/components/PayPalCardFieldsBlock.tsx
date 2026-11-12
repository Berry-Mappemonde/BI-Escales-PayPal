import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { authorizePledge, createPledge, fetchPledgeMode, fetchPledgeStatus, isVaultPledge, registerVault } from "../api/escales";
import type { PublicPledge } from "../api/types";
import type { PledgeFormValues } from "./PledgeButton";
import type { PayPalNamespace } from "../paypal/paypalSdk";

type FieldInstance = { render: (el: HTMLElement) => Promise<void>; close?: () => void | Promise<void> };

type CardFieldsFactory = (config: Record<string, unknown>) => {
  isEligible: () => boolean;
  NumberField: () => FieldInstance;
  ExpiryField: () => FieldInstance;
  CVVField: () => FieldInstance;
  NameField?: () => FieldInstance;
  submit: () => Promise<void>;
};

const CARD_ERROR_I18N: Record<string, string> = {
  "CARD AUTHENTICATION INCOMPLETE OR DECLINED": "pledge.cardErrorAuthentication",
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

function isExplicitCardDecline(error: unknown): boolean {
  if (error instanceof Error) return /\b(INSTRUMENT_DECLINED|CARD_DECLINED)\b|card authentication incomplete or declined/i.test(error.message);
  if (typeof error === "string") return /\b(INSTRUMENT_DECLINED|CARD_DECLINED)\b|card authentication incomplete or declined/i.test(error);
  if (!error || typeof error !== "object") return false;
  const body = error as { details?: { issue?: string }[]; code?: string };
  return [body.code, ...(Array.isArray(body.details) ? body.details.map(detail => detail.issue) : [])]
    .some(code => code === "INSTRUMENT_DECLINED" || code === "CARD_DECLINED");
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
  const nameRef = useRef<HTMLDivElement | null>(null);
  const postalRef = useRef("");
  const countryRef = useRef("FR");
  const valuesRef = useRef(values);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retryNotice, setRetryNotice] = useState<string | null>(null);
  const [postalCode, setPostalCode] = useState("");
  const [countryCode, setCountryCode] = useState("FR");
  const [confirmed, setConfirmed] = useState<PublicPledge | null>(null);
  const [paymentMode, setPaymentMode] = useState<string | null>(null);
  const activePledgeRef = useRef<PublicPledge | null>(null);
  const submitRef = useRef<(() => Promise<void>) | null>(null);
  const attemptRef = useRef<{ key: string; values: PledgeFormValues; pledge?: Promise<PublicPledge> } | null>(null);
  const submittingRef = useRef(false);
  const confirmationErrorRef = useRef<Error | null>(null);
  const confirmationDeclinedRef = useRef(false);
  const confirmationCanceledRef = useRef(false);
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
    const nameHost = nameRef.current;
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
        setPaymentMode(payment_mode);
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
          onApprove: (data: { liabilityShift?: string }) => {
            if (data?.liabilityShift === "UNKNOWN") confirmationErrorRef.current = new Error("Card authentication incomplete");
          },
          onError: (error: unknown) => {
            confirmationDeclinedRef.current = isExplicitCardDecline(error);
            confirmationErrorRef.current = new Error("Card confirmation failed");
          },
          onCancel: () => {
            confirmationCanceledRef.current = true;
          },
          billingAddress: () => {
            const country = countryRef.current.trim();
            return {
              countryCode: /^[A-Za-z]{2}$/.test(country) ? country.toUpperCase() : "FR",
              ...(postalRef.current.trim() ? { postalCode: postalRef.current.trim().toUpperCase() } : {}),
            };
          },
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
        if (!cancelled && nameHost && typeof cardFields.NameField === "function") {
          const instance = cardFields.NameField.call(cardFields);
          instances.push(instance);
          await instance.render(nameHost);
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
    setRetryNotice(null);
    try {
      confirmationErrorRef.current = null;
      confirmationDeclinedRef.current = false;
      confirmationCanceledRef.current = false;
      await submit();
      if (isClosed()) return;
      if (confirmationCanceledRef.current) {
        setRetryNotice(t("pledge.cardTryAgain"));
        return;
      }
      if (confirmationErrorRef.current) throw confirmationErrorRef.current;
      let current = activePledgeRef.current;
      if (!current) {
        throw new Error("pledge missing after card submit");
      }
      if (isVaultPledge(current)) {
        current = await registerVault(current.id, current.setup_token_id || undefined);
      } else {
        try {
          current = await authorizePledge(current.id);
        } catch (captureError) {
          // The server persists a decline before returning HTTP 409. A timeout
          // may also hide a completed/pending capture: read before any new charge.
          const stored = await fetchPledgeStatus(current.id).catch(() => null);
          if (isClosed()) return;
          if (stored && ["pending", "captured", "settled", "capture_failed"].includes(stored.status)) {
            current = { ...current, status: stored.status };
          } else {
            throw captureError;
          }
        }
      }
      if (isClosed()) return;
      if (current.status === "capture_failed" || current.status === "charge_failed") {
        // A definite decline starts a fresh pledge/order on the next Pay click.
        // Unknown transport outcomes keep their original key instead.
        attemptRef.current = null;
        activePledgeRef.current = null;
        throw new Error(t("pledge.cardCaptureNotCompleted"));
      }
      if ((current.payment_mode === "CAPTURE" || ["project_pledge", "common_fund"].includes(snapshot.kind || ""))
          && !["captured", "settled", "pending"].includes(current.status)) {
        throw new Error(t("pledge.cardCaptureNotCompleted"));
      }
      attemptRef.current = null;
      setReady(false);
      setConfirmed(current);
      onAuthorized?.(current);
    } catch (e) {
      if (!isClosed()) {
        if (confirmationDeclinedRef.current || isExplicitCardDecline(e)) {
          attemptRef.current = null;
          activePledgeRef.current = null;
        }
        setError(formatCardFieldError(e instanceof Error ? e.message : String(e), t));
      }
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
  const paidImmediately = confirmed?.status === "captured" || confirmed?.status === "settled";
  const paymentPending = confirmed?.status === "pending";
  const immediateDonation = paymentMode === "CAPTURE";

  return (
    <div className="paypal-card-fields" data-testid="paypal-card-fields" ref={rootRef}>
      {confirmed ? (
        <div data-testid="paypal-card-confirm">
          <p className="status">
            {t(paymentPending ? "pledge.cardConfirmPendingTitle" : paidImmediately ? "pledge.cardConfirmPaidTitle" : vaultConfirmed ? "pledge.cardConfirmVaultTitle" : "pledge.cardConfirmAuthorizeTitle")}
          </p>
          <p className="hint" data-testid="paypal-card-confirm-ref">
            {t("pledge.cardConfirmRef", { ref: shortRef })}
          </p>
          <p className="hint" data-testid="paypal-card-confirm-next">
            {t(paymentPending ? "pledge.cardConfirmPendingNext" : paidImmediately ? "pledge.cardConfirmPaidNext" : isCabinLegKind(confirmKind) ? "pledge.cardConfirmCabinNext" : "pledge.cardConfirmStopNext")}
          </p>
        </div>
      ) : null}
      <div data-testid="paypal-card-checkout" hidden={Boolean(confirmed)}>
        <p className="hint">{t(immediateDonation ? "pledge.cardFieldsImmediateHint" : "pledge.cardFieldsHint")}</p>
        <div className="card-field-row">
          <div ref={numberRef} data-testid="paypal-card-number" />
          <div ref={expiryRef} data-testid="paypal-card-expiry" />
          <div ref={cvvRef} data-testid="paypal-card-cvv" />
          <div ref={nameRef} data-testid="paypal-card-name" />
        </div>
        <label className="card-field-row">
          {t("pledge.cardPostalLabel")}
          <input
            data-testid="paypal-card-postal"
            autoComplete="postal-code"
            value={postalCode}
            onChange={(event) => {
              postalRef.current = event.target.value;
              setPostalCode(event.target.value);
            }}
          />
        </label>
        <label className="card-field-row">
          {t("pledge.cardCountryLabel")}
          <input
            data-testid="paypal-card-country"
            autoComplete="country"
            maxLength={2}
            value={countryCode}
            onChange={(event) => {
              countryRef.current = event.target.value;
              setCountryCode(event.target.value);
            }}
          />
        </label>
        <button
          type="button"
          data-testid="paypal-card-submit"
          disabled={!ready || busy || disabled}
          onClick={() => void onSubmit()}
        >
          {busy ? t("pledge.authorizing") : t("pledge.cardPay")}
        </button>
      </div>
      {retryNotice ? (
        <p className="notice" data-testid="paypal-card-retry">
          {retryNotice}
        </p>
      ) : null}
      {error ? (
        <p className="notice error">
          {t("pledge.error")}: {error}
        </p>
      ) : null}
    </div>
  );
}

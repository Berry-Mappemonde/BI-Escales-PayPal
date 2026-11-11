/**
 * PledgeButton on PayPal Web SDK v6. Rendered instead of the v5 inner component
 * only when the backend reports `features.paypal_js_v6` (see PledgeButton.tsx
 * and paypal/paypalJsVersion.ts). It is a copy of the v5 component, with the
 * same markup, test ids, copy and fallback redirect, and these differences:
 *
 *  - the SDK is the v6 adapter (paypal/v6/paypalSdkV6.ts): one core script,
 *    eligibility for the payment flow and the amount, payment sessions;
 *  - every checkout is remembered as an attempt (paypal/v6/checkoutAttempts.ts).
 *    An approval is always reconciled against the pledge it was made for, so an
 *    older PayPal window approved after the form was edited credits that older
 *    pledge and says so, never the edited form (audit finding F02);
 *  - a payer who comes back from a PayPal redirect is resumed by the v6 session
 *    and reconciled once with the server, shared with the App return handler
 *    (audit finding F01).
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { CabinLegPicker } from "./CabinLegPicker";
import { fetchFeatures, fetchPledgeMode, isVaultPledge } from "../api/escales";
import { PayPalCardFieldsBlock } from "./PayPalCardFieldsBlock";
import type { PublicPledge } from "../api/types";
import {
  loadPayPalSdk,
  payLaterEligible,
  safePayPalClose,
  safePayPalRender,
  type PayPalNamespace,
  type PayPalSdkButtonInstance,
} from "../paypal/v6/paypalSdkV6";
import {
  rememberAttempt,
  returnedAttempt,
  reconcileAttempt,
  type CheckoutAttempt,
} from "../paypal/v6/checkoutAttempts";
import { createPledgeWithTimeout, pledgeCreateErrorMessage } from "../paypal/pledgeCreate";
import { PayPalWalletPayBlockV6 } from "./PayPalWalletPayBlockV6";
import { subscribePledgeReturn } from "../paypal/pledgeReturnEvents";
import { approvedStatusKey, type PledgeButtonProps, type PledgeFormValues } from "./PledgeButton";

/** The amount, currency and target an attempt was made for: what the payer approved in PayPal. */
function sameCheckout(attempt: CheckoutAttempt, revision: number, values: PledgeFormValues): boolean {
  return (
    attempt.revision === revision
    && attempt.amount === values.amount_eur
    && attempt.currency === (values.currency || "EUR")
    && attempt.target === (values.target_id || "")
    && attempt.milestone === values.milestone_id
  );
}

export function PledgeButtonV6Inner({ values, disabled, onAuthorized }: PledgeButtonProps) {
  const { t, i18n } = useTranslation();
  const appLang = String(i18n.language || "fr").startsWith("en") ? "en" : "fr";
  const [created, setCreated] = useState<PublicPledge | null>(null);
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);
  /** Shown when PayPal approved an older attempt than the form now on screen (F02). */
  const [originalReceipt, setOriginalReceipt] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [paypal, setPaypal] = useState<PayPalNamespace | null>(null);
  const sdkReady = paypal !== null;
  const [smartButtonsReady, setSmartButtonsReady] = useState(false);
  const [pledgeMode, setPledgeMode] = useState<{
    milestoneId: string;
    kind: string | undefined;
    paymentMode: "AUTHORIZE" | "VAULT";
  } | null>(null);
  const [cardFieldsEnabled, setCardFieldsEnabled] = useState(false);
  const [walletPayEnabled, setWalletPayEnabled] = useState(false);
  // Load the SDK once the feature flags are known, so a wallet_pay flip does not load a second SDK.
  const [featuresKnown, setFeaturesKnown] = useState(false);
  const sdkHost = useRef<HTMLDivElement | null>(null);
  const activePledgeIdRef = useRef<string | null>(null);
  const vault = created ? isVaultPledge(created) : false;
  const isProjectPledge = (values.kind || "") === "project_pledge";
  const isCabinLeg = (values.kind || "") === "cabin_leg";
  const [cabinLegId, setCabinLegId] = useState("");
  const sdkIntent = isProjectPledge ? "capture" : "authorize";
  const sdkCurrency =
    isProjectPledge && values.currency?.trim()
      ? values.currency.trim().toUpperCase()
      : "EUR";
  const effectiveMilestoneId = isCabinLeg ? cabinLegId : values.milestone_id;
  const effectiveValues = useMemo(
    () => ({
      ...values,
      milestone_id: effectiveMilestoneId,
      target_id: isCabinLeg ? effectiveMilestoneId : values.target_id,
    }),
    [values, isCabinLeg, effectiveMilestoneId],
  );
  const cabinLegReady = !isCabinLeg || Boolean(cabinLegId.trim());
  const checkoutDisabled = Boolean(disabled || busy || !cabinLegReady);
  // Smart Buttons must not depend on `busy`: their own createOrder sets busy, and tearing the
  // buttons down mid-checkout closes the PayPal window and leaves "Creating pledge…" stuck.
  const smartButtonsBlocked = Boolean(disabled || !cabinLegReady);
  const modeMatchesValues =
    pledgeMode?.milestoneId === effectiveMilestoneId && pledgeMode.kind === values.kind;
  // v6 asks eligibility for a payment flow (and, one-time, an amount) instead of loading a "vault" SDK URL.
  const sdkPaymentFlow =
    !isProjectPledge && modeMatchesValues && pledgeMode?.paymentMode === "VAULT"
      ? "VAULT_WITHOUT_PAYMENT"
      : "ONE_TIME_PAYMENT";
  const shouldRenderSmartButtons =
    isProjectPledge
    || (modeMatchesValues && pledgeMode.paymentMode === "AUTHORIZE")
    || (isCabinLeg && modeMatchesValues && pledgeMode.paymentMode === "VAULT");
  const intentLabel = isProjectPledge
    ? t("pledge.intentProject")
    : modeMatchesValues
      ? t(pledgeMode.paymentMode === "VAULT" ? "pledge.intentVault" : "pledge.intent")
      : null;
  const buttonsHost = useRef<HTMLDivElement | null>(null);
  const valuesRef = useRef(effectiveValues);
  valuesRef.current = effectiveValues;
  // Bumped on every amount/target change; an order answered for an older revision is dropped.
  const formRevisionRef = useRef(0);

  useEffect(() => {
    let cancelled = false;
    void fetchFeatures()
      .then((flags) => {
        if (!cancelled) {
          setCardFieldsEnabled(Boolean(flags.card_fields));
          setWalletPayEnabled(Boolean(flags.wallet_pay));
          setFeaturesKnown(true);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setCardFieldsEnabled(false);
          setFeaturesKnown(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const clientId = String(import.meta.env.VITE_PAYPAL_CLIENT_ID ?? "").trim();
    setPaypal(null);
    if (!clientId || !featuresKnown) {
      return () => {
        cancelled = true;
      };
    }
    void loadPayPalSdk(clientId, appLang, sdkIntent, walletPayEnabled, sdkCurrency, sdkPaymentFlow, values.amount_eur)
      .then((ns) => {
        if (!cancelled) setPaypal(ns);
      })
      .catch(() => {
        if (!cancelled) setPaypal(null);
      });
    return () => {
      cancelled = true;
    };
  }, [appLang, sdkIntent, sdkCurrency, sdkPaymentFlow, walletPayEnabled, featuresKnown, values.amount_eur]);

  useEffect(() => {
    formRevisionRef.current += 1;
    setCreated(null);
    setStatus(null);
    setError(null);
    setBusy(false);
    activePledgeIdRef.current = null;
  }, [values.amount_eur, values.currency, values.kind, values.milestone_id, values.description, values.target_id, cabinLegId]);

  useEffect(() => {
    if (!isCabinLeg) {
      setCabinLegId("");
      return;
    }
    const candidate = String(values.milestone_id || "").trim();
    if (candidate.startsWith("leg-")) {
      setCabinLegId(candidate);
    } else {
      setCabinLegId("");
    }
  }, [isCabinLeg, values.kind, values.milestone_id]);

  useEffect(() => {
    let cancelled = false;
    setPledgeMode(null);
    if (isProjectPledge) {
      return () => {
        cancelled = true;
      };
    }
    if (isCabinLeg && !effectiveMilestoneId.trim()) {
      return () => {
        cancelled = true;
      };
    }
    void fetchPledgeMode(effectiveMilestoneId, values.kind)
      .then(({ payment_mode }) => {
        if (!cancelled) {
          setPledgeMode({
            milestoneId: effectiveMilestoneId,
            kind: values.kind,
            paymentMode: payment_mode,
          });
        }
      })
      .catch(() => {
        if (!cancelled) setPledgeMode(null);
      });
    return () => {
      cancelled = true;
    };
  }, [isProjectPledge, isCabinLeg, effectiveMilestoneId, values.kind]);

  useEffect(() => {
    if (!created?.approve_link || !vault || smartButtonsReady) return;
    window.location.assign(created.approve_link);
  }, [created, vault, smartButtonsReady]);

  useEffect(() => {
    return subscribePledgeReturn((detail) => {
      const activeId = activePledgeIdRef.current || created?.id;
      if (activeId && detail.pledgeId !== activeId) return;
      setBusy(false);
      setStatus(null);
      setCreated(null);
      activePledgeIdRef.current = null;
      if (detail.outcome === "error") {
        setError(detail.message || t("pledge.error"));
      } else {
        setError(null);
      }
    });
  }, [created?.id, t]);

  const resetPledgeAttempt = () => {
    setCreated(null);
    setStatus(null);
    setError(null);
    setBusy(false);
    activePledgeIdRef.current = null;
  };

  const createOrder = async () => {
    const revision = formRevisionRef.current;
    const isStale = () => revision !== formRevisionRef.current;
    setBusy(true);
    setError(null);
    setStatus(t("pledge.creating"));
    try {
      const v = valuesRef.current;
      const pledge = await createPledgeWithTimeout(
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
      // The form changed while this order was being created: never show its old approve link.
      if (isStale()) return;
      if (!pledge.approve_link) throw new Error("approve_link missing");
      activePledgeIdRef.current = pledge.id;
      setCreated(pledge);
      if (isVaultPledge(pledge)) {
        setStatus(t("pledge.vaultRedirect"));
      } else if (isProjectPledge) {
        setStatus(t("pledge.returnPendingProject"));
      } else {
        setStatus(t("pledge.returnPending"));
      }
    } catch (e) {
      if (isStale()) return;
      activePledgeIdRef.current = null;
      setCreated(null);
      setStatus(null);
      setError(pledgeCreateErrorMessage(e, t));
    } finally {
      if (!isStale()) setBusy(false);
    }
  };

  /** In-page Smart Buttons (PayPal wallet, Pay Later, card): no approve_link redirect. */
  useEffect(() => {
    setSmartButtonsReady(false);
    const host = buttonsHost.current;
    if (!host) return;
    host.innerHTML = "";
    if (!paypal || !shouldRenderSmartButtons || smartButtonsBlocked) return;
    const vaultSmartButtons = isCabinLeg && modeMatchesValues && pledgeMode?.paymentMode === "VAULT";
    let attempt: CheckoutAttempt | undefined;
    const remember = (pledge: PublicPledge, revision: number, v: PledgeFormValues, mode: "AUTHORIZE" | "VAULT") => {
      attempt = rememberAttempt({
        key: crypto.randomUUID(),
        revision,
        pledgeId: pledge.id,
        orderId: pledge.order_id || undefined,
        amount: v.amount_eur,
        currency: v.currency || "EUR",
        milestone: v.milestone_id,
        target: v.target_id || "",
        label: v.description || undefined,
        mode,
        path: location.pathname,
      });
    };
    /**
     * PayPal approved a checkout. Reconcile the pledge that checkout was made for
     * (this window's attempt, or the one a redirect return belongs to), never the
     * pledge of whatever the form shows now.
     */
    const approveOriginal = async (data?: { orderId?: string }) => {
      const original = attempt || returnedAttempt(data?.orderId, vaultSmartButtons ? "VAULT" : "AUTHORIZE");
      if (!original || (data?.orderId && original.orderId && data.orderId !== original.orderId)) {
        throw new Error("Checkout return could not be correlated");
      }
      const current = () => sameCheckout(original, formRevisionRef.current, valuesRef.current);
      if (current()) {
        setBusy(true);
        setError(null);
        if (original.mode === "VAULT") setStatus(t("pledge.vaulting"));
      }
      try {
        const done = await reconcileAttempt(original.pledgeId, original.mode === "VAULT");
        if (!mountedRef.current) return;
        if (!current()) {
          // The form moved on while PayPal was open: the older pledge is what was approved.
          setOriginalReceipt(
            t("pledge.originalReceipt", {
              id: original.pledgeId,
              amount: original.amount,
              currency: original.currency,
              target: original.label || original.target || original.milestone,
            }),
          );
          return;
        }
        if (original.mode === "VAULT") {
          setCreated(done);
          setStatus(t("pledge.vaultSaved"));
        } else {
          const doneKey = approvedStatusKey(done?.status);
          setStatus(doneKey ? t(doneKey) : null);
        }
        onAuthorized?.(done);
      } catch (e) {
        if (mountedRef.current && current()) {
          // Nothing is being prepared any more: the error is the whole message.
          setStatus(null);
          setError(e instanceof Error ? e.message : String(e));
        }
        throw e;
      } finally {
        if (mountedRef.current && current()) setBusy(false);
      }
    };
    let closed = false;
    let buttons: PayPalSdkButtonInstance | null = null;
    const smartCallbacks = vaultSmartButtons
      ? {
          createVaultSetupToken: async () => {
            const revision = formRevisionRef.current;
            setBusy(true);
            setError(null);
            setStatus(t("pledge.creating"));
            try {
              const v = valuesRef.current;
              const pledge = await createPledgeWithTimeout(
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
              if (revision !== formRevisionRef.current) {
                throw new Error("pledge form changed, order discarded");
              }
              if (!isVaultPledge(pledge) || !pledge.setup_token_id) throw new Error("setup_token_id missing");
              remember(pledge, revision, v, "VAULT");
              activePledgeIdRef.current = pledge.id;
              setCreated(pledge);
              return pledge.setup_token_id;
            } catch (e) {
              setStatus(null);
              setError(pledgeCreateErrorMessage(e, t));
              throw e;
            } finally {
              setBusy(false);
            }
          },
          onApprove: approveOriginal,
        }
      : {
          createOrder: async () => {
            const revision = formRevisionRef.current;
            setBusy(true);
            setError(null);
            setStatus(t("pledge.creating"));
            try {
              const v = valuesRef.current;
              const pledge = await createPledgeWithTimeout(
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
              if (revision !== formRevisionRef.current) {
                throw new Error("pledge form changed, order discarded");
              }
              if (!pledge.order_id) throw new Error("order_id missing");
              remember(pledge, revision, v, "AUTHORIZE");
              activePledgeIdRef.current = pledge.id;
              return pledge.order_id;
            } catch (e) {
              setStatus(null);
              setError(pledgeCreateErrorMessage(e, t));
              throw e;
            } finally {
              setBusy(false);
            }
          },
          onApprove: approveOriginal,
        };
    void safePayPalRender(
      paypal.Buttons,
      {
        style: { layout: "vertical", label: isProjectPledge ? "donate" : "pay" },
        offerPayLater: isProjectPledge && payLaterEligible(values.amount_eur, values.kind),
        ...smartCallbacks,
        onCancel: () => {
          setStatus(null);
          setBusy(false);
        },
        onError: (err: unknown) => {
          setError(err instanceof Error ? err.message : String(err));
          setBusy(false);
        },
      },
      host,
    ).then((result) => {
      buttons = result.instance;
      if (closed) safePayPalClose(buttons);
      else if (result.ok) {
        host.dataset.smartButtons = "1";
        setSmartButtonsReady(true);
      }
    });
    return () => {
      closed = true;
      safePayPalClose(buttons);
    };
  }, [
    paypal,
    shouldRenderSmartButtons,
    smartButtonsBlocked,
    isProjectPledge,
    isCabinLeg,
    modeMatchesValues,
    pledgeMode?.paymentMode,
    appLang,
    t,
    onAuthorized,
  ]);

  const confirmVault = async () => {
    if (!created || !vault) return;
    setBusy(true);
    setError(null);
    try {
      setStatus(t("pledge.vaulting"));
      const saved = await reconcileAttempt(created.id, true);
      setCreated(saved);
      setStatus(t("pledge.vaultSaved"));
      onAuthorized?.(saved);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    if (!sdkReady || !sdkHost.current) return;
    sdkHost.current.dataset.paypalSdkReady = "1";
    const host = sdkHost.current;
    host.innerHTML = "";
    if (paypal && payLaterEligible(values.amount_eur, values.kind)) {
      void safePayPalRender(
        paypal.Messages,
        {
          amount: values.amount_eur.replace(",", "."),
          currencyCode: sdkCurrency,
          placement: "product",
          style: { layout: "text" },
        },
        host,
      ).then((result) => {
        if (result.ok) host.dataset.payLaterMessages = "1";
      });
    }
  }, [paypal, sdkReady, values.amount_eur, values.kind, sdkCurrency]);

  return (
    <div className="pledge-button" data-testid="paypal-buttons" data-kind={values.kind || ""} data-paypal-js="v6">
      {intentLabel ? <p className="hint">{intentLabel}</p> : null}
      <p className="hint">{t("pledge.venmoNote")}</p>
      {originalReceipt ? (
        <p className="notice" role="status" data-testid="pledge-original-receipt">
          {originalReceipt}
        </p>
      ) : null}
      {isCabinLeg ? (
        <CabinLegPicker
          value={cabinLegId}
          onChange={setCabinLegId}
          disabled={busy}
        />
      ) : null}
      {!smartButtonsReady ? (
        <button type="button" onClick={() => void createOrder()} disabled={checkoutDisabled}>
          {t("pledge.create")}
        </button>
      ) : null}
      {created?.approve_link && !vault ? (
        <a href={created.approve_link} rel="noreferrer" data-testid="paypal-approve-link">
          {t("pledge.approve")}
        </a>
      ) : null}
      {vault && created?.approve_link && !smartButtonsReady ? (
        <a href={created.approve_link} rel="noreferrer" data-testid="paypal-approve-link">
          {t("pledge.vaultApprove")}
        </a>
      ) : null}
      {vault && !smartButtonsReady ? (
        <button type="button" data-testid="pledge-authorize" onClick={() => void confirmVault()} disabled={busy}>
          {t("pledge.vaultConfirm")}
        </button>
      ) : null}
      <div ref={buttonsHost} data-testid="paypal-smart-buttons" />
      {walletPayEnabled && !isProjectPledge && modeMatchesValues && pledgeMode?.paymentMode !== "VAULT" ? (
        <PayPalWalletPayBlockV6
          values={effectiveValues}
          appLang={appLang}
          sdkIntent={sdkIntent}
          sdkReady={sdkReady}
          paypal={paypal}
          disabled={checkoutDisabled}
          onAuthorized={onAuthorized}
        />
      ) : null}
      {cardFieldsEnabled && !isProjectPledge ? (
        <PayPalCardFieldsBlock
          values={effectiveValues}
          appLang={appLang}
          paypal={paypal}
          disabled={checkoutDisabled}
          onAuthorized={onAuthorized}
        />
      ) : null}
      <div ref={sdkHost} data-testid="paypal-sdk-host" />
      {status ? <p className="status">{status}</p> : null}
      {error ? (
        <div className="notice error">
          <p>
            {t("pledge.error")}: {error}
          </p>
          <button type="button" data-testid="pledge-retry" onClick={resetPledgeAttempt} disabled={busy}>
            {t("pledge.retry")}
          </button>
        </div>
      ) : null}
    </div>
  );
}

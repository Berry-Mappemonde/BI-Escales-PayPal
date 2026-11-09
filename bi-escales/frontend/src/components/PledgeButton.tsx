import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { CabinLegPicker } from "./CabinLegPicker";
import {
  authorizePledge,
  createPledge,
  fetchFeatures,
  fetchPledgeMode,
  registerVault,
  isVaultPledge,
} from "../api/escales";
import { PayPalCardFieldsBlock } from "./PayPalCardFieldsBlock";
import type { PublicPledge } from "../api/types";
import {
  loadPayPalSdk,
  payLaterEligible,
  safePayPalClose,
  safePayPalRender,
  type PayPalNamespace,
  type PayPalSdkButtonInstance,
} from "../paypal/paypalSdk";
import { PayPalErrorBoundary } from "./PayPalErrorBoundary";
import { PayPalWalletPayBlock } from "./PayPalWalletPayBlock";
import { subscribePledgeReturn } from "../paypal/pledgeReturnEvents";

export interface PledgeFormValues {
  quantity?: number;
  amount_eur: string;
  currency?: string;
  description: string;
  milestone_id: string;
  contributor?: string;
  kind?: string;
  target_id?: string;
  lang?: string;
}

export interface PledgeButtonProps {
  values: PledgeFormValues;
  disabled?: boolean;
  onAuthorized?: (pledge: PublicPledge) => void;
}

export function PledgeButton(props: PledgeButtonProps) {
  return (
    <PayPalErrorBoundary testId="paypal-buttons-error">
      <PledgeButtonInner {...props} />
    </PayPalErrorBoundary>
  );
}

function PledgeButtonInner({ values, disabled, onAuthorized }: PledgeButtonProps) {
  const { t, i18n } = useTranslation();
  const appLang = String(i18n.language || "fr").startsWith("en") ? "en" : "fr";
  const [created, setCreated] = useState<PublicPledge | null>(null);
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
    void loadPayPalSdk(clientId, appLang, sdkIntent, walletPayEnabled, sdkCurrency, pledgeMode?.paymentMode === "VAULT" ? "VAULT_WITHOUT_PAYMENT" : "ONE_TIME_PAYMENT")
      .then((ns) => {
        if (!cancelled) setPaypal(ns);
      })
      .catch(() => {
        if (!cancelled) setPaypal(null);
      });
    return () => {
      cancelled = true;
    };
  }, [appLang, sdkIntent, sdkCurrency, walletPayEnabled, featuresKnown, pledgeMode?.paymentMode]);

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

  const createOrder = async () => {
    const revision = formRevisionRef.current;
    const isStale = () => revision !== formRevisionRef.current;
    setBusy(true);
    setError(null);
    setStatus(t("pledge.creating"));
    try {
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
      setError(e instanceof Error ? e.message : String(e));
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
    let pledgeId: string | null = null;
    let closed = false;
    let buttons: PayPalSdkButtonInstance | null = null;
    const smartCallbacks = vaultSmartButtons
      ? {
          createVaultSetupToken: async () => {
            const revision = formRevisionRef.current;
            setBusy(true);
            setError(null);
            setStatus(t("pledge.creating"));
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
            if (revision !== formRevisionRef.current) {
              throw new Error("pledge form changed, order discarded");
            }
            if (!isVaultPledge(pledge) || !pledge.setup_token_id) throw new Error("setup_token_id missing");
            pledgeId = pledge.id;
            activePledgeIdRef.current = pledge.id;
            setCreated(pledge);
            setBusy(false);
            return pledge.setup_token_id;
          },
          onApprove: async () => {
            if (!pledgeId) return;
            setBusy(true);
            setError(null);
            try {
              setStatus(t("pledge.vaulting"));
              const saved = await registerVault(pledgeId);
              setCreated(saved);
              setStatus(t("pledge.vaultSaved"));
              onAuthorized?.(saved);
            } catch (e) {
              setError(e instanceof Error ? e.message : String(e));
            } finally {
              setBusy(false);
            }
          },
        }
      : {
          createOrder: async () => {
            const revision = formRevisionRef.current;
            setBusy(true);
            setError(null);
            setStatus(t("pledge.creating"));
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
            if (revision !== formRevisionRef.current) {
              throw new Error("pledge form changed, order discarded");
            }
            if (!pledge.order_id) throw new Error("order_id missing");
            pledgeId = pledge.id;
            activePledgeIdRef.current = pledge.id;
            setBusy(false);
            return pledge.order_id;
          },
          onApprove: async () => {
            if (!pledgeId) return;
            setBusy(true);
            try {
              const done = await authorizePledge(pledgeId);
              setStatus(isProjectPledge ? t("pledge.returnPendingProject") : t("pledge.returnPending"));
              onAuthorized?.(done);
            } catch (e) {
              setError(e instanceof Error ? e.message : String(e));
            } finally {
              setBusy(false);
            }
          },
        };
    void safePayPalRender(
      paypal.Buttons,
      {
        style: { layout: "vertical", label: isProjectPledge ? "donate" : "pay" },
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
      const saved = await registerVault(created.id);
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
    <div className="pledge-button" data-testid="paypal-buttons" data-kind={values.kind || ""}>
      {intentLabel ? <p className="hint">{intentLabel}</p> : null}
      <p className="hint">{t("pledge.venmoNote")}</p>
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
        <PayPalWalletPayBlock
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
        <p className="notice error">
          {t("pledge.error")}: {error}
        </p>
      ) : null}
    </div>
  );
}

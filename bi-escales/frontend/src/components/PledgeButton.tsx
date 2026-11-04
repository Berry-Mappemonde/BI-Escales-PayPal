import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { createPledge, registerVault, isVaultPledge } from "../api/escales";
import type { PublicPledge } from "../api/types";
import { loadPayPalSdk, payLaterEligible } from "../paypal/paypalSdk";
import { subscribePledgeReturn } from "../paypal/pledgeReturnEvents";

export interface PledgeFormValues {
  amount_eur: string;
  description: string;
  milestone_id: string;
  contributor?: string;
  kind?: string;
  target_id?: string;
}

export interface PledgeButtonProps {
  values: PledgeFormValues;
  disabled?: boolean;
  onAuthorized?: (pledge: PublicPledge) => void;
}

export function PledgeButton({ values, disabled, onAuthorized }: PledgeButtonProps) {
  const { t } = useTranslation();
  const [created, setCreated] = useState<PublicPledge | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [sdkReady, setSdkReady] = useState(false);
  const sdkHost = useRef<HTMLDivElement | null>(null);
  const activePledgeIdRef = useRef<string | null>(null);
  const vault = created ? isVaultPledge(created) : false;

  useEffect(() => {
    let cancelled = false;
    const clientId = String(import.meta.env.VITE_PAYPAL_CLIENT_ID ?? "").trim();
    if (!clientId) {
      setSdkReady(false);
      return () => {
        cancelled = true;
      };
    }
    void loadPayPalSdk(clientId)
      .then(() => {
        if (!cancelled) setSdkReady(true);
      })
      .catch(() => {
        if (!cancelled) setSdkReady(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!created?.approve_link || !vault) return;
    window.location.assign(created.approve_link);
  }, [created, vault]);

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
    setBusy(true);
    setError(null);
    setStatus(t("pledge.creating"));
    try {
      const pledge = await createPledge(
        {
          amount_eur: values.amount_eur,
          description: values.description,
          milestone_id: values.milestone_id,
          contributor: values.contributor?.trim() || undefined,
          kind: values.kind,
          target_id: values.target_id,
        },
        crypto.randomUUID(),
      );
      if (!pledge.approve_link) throw new Error("approve_link missing");
      activePledgeIdRef.current = pledge.id;
      setCreated(pledge);
      if (isVaultPledge(pledge)) {
        setStatus(t("pledge.vaultRedirect"));
      } else {
        setStatus(t("pledge.returnPending"));
      }
    } catch (e) {
      activePledgeIdRef.current = null;
      setCreated(null);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

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
    if (payLaterEligible(values.amount_eur, values.kind) && window.paypal?.Messages) {
      const messages = window.paypal.Messages({
        amount: values.amount_eur.replace(",", "."),
        placement: "product",
        style: { layout: "text" },
      });
      void messages.render(host);
      host.dataset.payLaterMessages = "1";
    }
  }, [sdkReady, values.amount_eur, values.kind]);

  return (
    <div className="pledge-button" data-testid="paypal-buttons" data-kind={values.kind || ""}>
      <p className="hint">{t("pledge.intent")}</p>
      <p className="hint">{t("pledge.venmoNote")}</p>
      <button type="button" onClick={() => void createOrder()} disabled={disabled || busy}>
        {t("pledge.create")}
      </button>
      {created?.approve_link && !vault ? (
        <a href={created.approve_link} rel="noreferrer" data-testid="paypal-approve-link">
          {t("pledge.approve")}
        </a>
      ) : null}
      {vault && created?.approve_link ? (
        <a href={created.approve_link} rel="noreferrer" data-testid="paypal-approve-link">
          {t("pledge.vaultApprove")}
        </a>
      ) : null}
      {vault ? (
        <button type="button" data-testid="pledge-authorize" onClick={() => void confirmVault()} disabled={busy}>
          {t("pledge.vaultConfirm")}
        </button>
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

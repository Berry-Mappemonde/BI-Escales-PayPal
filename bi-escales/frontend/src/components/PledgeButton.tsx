import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { createPledge, fetchFeatures, isVaultPledge, registerVault } from "../api/escales";
import type { PublicPledge } from "../api/types";
import { loadPayPalSdk } from "../paypal/paypalSdk";

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
  const vault = created ? isVaultPledge(created) : false;

  useEffect(() => {
    let cancelled = false;
    void fetchFeatures()
      .then((flags) => {
        const clientId = (flags.paypal_client_id || "").trim();
        if (!clientId || cancelled) return;
        return loadPayPalSdk(clientId).then(() => {
          if (!cancelled) setSdkReady(true);
        });
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
      setCreated(pledge);
      if (isVaultPledge(pledge)) {
        setStatus(t("pledge.vaultRedirect"));
      } else {
        setStatus(t("pledge.returnPending"));
      }
    } catch (e) {
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
  }, [sdkReady]);

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

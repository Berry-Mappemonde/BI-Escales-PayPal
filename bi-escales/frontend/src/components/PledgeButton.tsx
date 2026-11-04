import { useState } from "react";
import { useTranslation } from "react-i18next";
import { authorizePledge, createPledge, isVaultPledge, registerVault } from "../api/escales";
import type { PublicPledge } from "../api/types";

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
  const [opened, setOpened] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const createOrder = async () => {
    setBusy(true);
    setError(null);
    setStatus(t("pledge.creating"));
    setOpened(false);
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
      setStatus(null);
    } catch (e) {
      setCreated(null);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const confirmAfterApproval = async () => {
    if (!created || !opened) return;
    setBusy(true);
    setError(null);
    try {
      if (isVaultPledge(created)) {
        setStatus(t("pledge.vaulting"));
        const saved = await registerVault(created.id);
        setCreated(saved);
        setStatus(t("pledge.vaulted"));
        onAuthorized?.(saved);
        return;
      }
      setStatus(t("pledge.authorizing"));
      const authorized = await authorizePledge(created.id);
      setCreated(authorized);
      setStatus(t("pledge.authorized"));
      onAuthorized?.(authorized);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="pledge-button" data-testid="paypal-buttons">
      <p className="hint">{t("pledge.intent")}</p>
      <button type="button" onClick={() => void createOrder()} disabled={disabled || busy}>
        {t("pledge.create")}
      </button>
      {created?.approve_link ? (
        <a
          href={created.approve_link}
          target="_blank"
          rel="noreferrer"
          data-testid="paypal-approve-link"
          onClick={() => setOpened(true)}
        >
          {t("pledge.approve")}
        </a>
      ) : null}
      <button
        type="button"
        data-testid="pledge-authorize"
        onClick={() => void confirmAfterApproval()}
        disabled={!created || !opened || busy}
      >
        {created && isVaultPledge(created) ? t("pledge.vaultConfirm") : t("pledge.authorize")}
      </button>
      {status ? <p className="status">{status}</p> : null}
      {error ? (
        <p className="notice error">
          {t("pledge.error")}: {error}
        </p>
      ) : null}
    </div>
  );
}

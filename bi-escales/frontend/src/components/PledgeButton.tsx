import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { authorizePledge, createPledge, isVaultPledge, registerVault } from "../api/escales";
import type { PublicPledge } from "../api/types";
import { paypalClientId } from "../config/features";
import { loadPayPalSdk } from "../paypal/sdk";

export interface PledgeFormValues {
  amount_eur: string;
  description: string;
  milestone_id: string;
  contributor?: string;
}

export interface PledgeButtonProps {
  values: PledgeFormValues;
  disabled?: boolean;
  onAuthorized?: (pledge: PublicPledge) => void;
}

export function PledgeButton({ values, disabled, onAuthorized }: PledgeButtonProps) {
  const { t } = useTranslation();
  const containerRef = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const clientId = paypalClientId();
  const valuesRef = useRef(values);
  valuesRef.current = values;
  const onAuthorizedRef = useRef(onAuthorized);
  onAuthorizedRef.current = onAuthorized;
  const pledgeRef = useRef<PublicPledge | null>(null);
  const [vaultPledge, setVaultPledge] = useState<PublicPledge | null>(null);
  const paypalMock = import.meta.env.VITE_PAYPAL_MOCK === "1";

  const runDemoApprove = async () => {
    setError(null);
    setStatus(t("pledge.creating"));
    try {
      const requestId = crypto.randomUUID();
      const pledge = await createPledge(valuesRef.current, requestId);
      pledgeRef.current = pledge;
      if (isVaultPledge(pledge)) {
        setVaultPledge(pledge);
        setStatus(null);
        return;
      }
      if (!pledge.order_id) throw new Error("order_id missing");
      setVaultPledge(null);
      setStatus(t("pledge.authorizing"));
      const authorized = await authorizePledge(pledge.id);
      setStatus(t("pledge.authorized"));
      onAuthorizedRef.current?.(authorized);
    } catch (e) {
      setStatus(null);
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  useEffect(() => {
    if (paypalMock || !clientId || disabled) return;
    let cancelled = false;

    const mount = async () => {
      setError(null);
      setStatus(null);
      if (!containerRef.current) return;
      containerRef.current.innerHTML = "";
      try {
        const paypal = await loadPayPalSdk(clientId);
        if (cancelled || !containerRef.current) return;
        const buttons = paypal.Buttons({
          createOrder: async () => {
            setStatus(t("pledge.creating"));
            const requestId = crypto.randomUUID();
            const pledge = await createPledge(valuesRef.current, requestId);
            pledgeRef.current = pledge;
            if (isVaultPledge(pledge)) {
              setVaultPledge(pledge);
              throw new Error("VAULT_SETUP");
            }
            if (!pledge.order_id) throw new Error("order_id missing");
            setVaultPledge(null);
            return pledge.order_id;
          },
          onApprove: async () => {
            const pledge = pledgeRef.current;
            if (!pledge) throw new Error("pledge missing");
            setStatus(t("pledge.authorizing"));
            const authorized = await authorizePledge(pledge.id);
            setStatus(t("pledge.authorized"));
            onAuthorizedRef.current?.(authorized);
          },
          onError: (err) => {
            const message = err instanceof Error ? err.message : String(err);
            if (message.includes("VAULT_SETUP")) return;
            setError(message);
          },
          onCancel: () => {
            setStatus(null);
          },
        });
        await buttons.render(containerRef.current);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    };

    void mount();
    return () => {
      cancelled = true;
      if (containerRef.current) containerRef.current.innerHTML = "";
    };
  }, [clientId, disabled, paypalMock, t]);

  const confirmVault = async () => {
    if (!vaultPledge) return;
    setError(null);
    setStatus(t("pledge.vaulting"));
    try {
      const saved = await registerVault(vaultPledge.id);
      setVaultPledge(saved);
      setStatus(t("pledge.vaulted"));
      onAuthorizedRef.current?.(saved);
    } catch (e) {
      setStatus(null);
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  if (!paypalMock && !clientId) {
    return <p className="notice warn">{t("pledge.missingClientId")}</p>;
  }

  return (
    <div className="pledge-button">
      <p className="hint">{paypalMock ? t("pledge.demoIntent") : t("pledge.intent")}</p>
      {paypalMock ? (
        <button type="button" data-testid="paypal-demo-approve" onClick={() => void runDemoApprove()} disabled={disabled}>
          {t("pledge.demoApprove")}
        </button>
      ) : (
        <div ref={containerRef} data-testid="paypal-buttons" />
      )}
      {vaultPledge ? (
        <div className="vault-setup" data-testid="vault-setup">
          <p className="hint">{t("pledge.vaultHint")}</p>
          {vaultPledge.approve_link ? (
            <a href={vaultPledge.approve_link} target="_blank" rel="noreferrer">
              {t("pledge.vaultApprove")}
            </a>
          ) : null}
          <button type="button" onClick={() => void confirmVault()}>
            {t("pledge.vaultConfirm")}
          </button>
        </div>
      ) : null}
      {status ? (
        <p className="status" data-testid="pledge-status">
          {status}
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

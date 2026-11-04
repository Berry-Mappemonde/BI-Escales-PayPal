import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { authorizePledge, createPledge } from "../api/escales";
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

  useEffect(() => {
    if (!clientId || disabled) return;
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
            if (!pledge.order_id) throw new Error("order_id missing");
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
            setError(err instanceof Error ? err.message : String(err));
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
  }, [clientId, disabled, t]);

  if (!clientId) {
    return <p className="notice warn">{t("pledge.missingClientId")}</p>;
  }

  return (
    <div className="pledge-button">
      <p className="hint">{t("pledge.intent")}</p>
      <div ref={containerRef} data-testid="paypal-buttons" />
      {status ? <p className="status">{status}</p> : null}
      {error ? (
        <p className="notice error">
          {t("pledge.error")}: {error}
        </p>
      ) : null}
    </div>
  );
}

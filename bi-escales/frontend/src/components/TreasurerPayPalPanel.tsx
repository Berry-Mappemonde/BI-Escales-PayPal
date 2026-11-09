import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  fetchCrewSupporterPlan,
  fetchPayPalDisputes,
  fetchPayPalInvoices,
  fetchPayPalSubscriptions,
  setupCrewSubscription,
} from "../api/escales";

export interface TreasurerPayPalPanelProps {
  adminKey: string;
}

export function TreasurerPayPalPanel({ adminKey }: TreasurerPayPalPanelProps) {
  const { t } = useTranslation();
  const [disputeCount, setDisputeCount] = useState<number | null>(null);
  const [invoiceCount, setInvoiceCount] = useState<number | null>(null);
  const [subscriptions, setSubscriptions] = useState<number | null>(null);
  const [setupNote, setSetupNote] = useState<string | null>(null);
  const [crewPlanConfigured, setCrewPlanConfigured] = useState<boolean | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const key = adminKey.trim();
    if (!key) {
      setDisputeCount(null);
      setInvoiceCount(null);
      setSubscriptions(null);
      return;
    }
    setError(null);
    try {
      const [disputes, invoices, subs] = await Promise.all([
        fetchPayPalDisputes(key),
        fetchPayPalInvoices(key),
        fetchPayPalSubscriptions(key),
      ]);
      const dItems = disputes.paypal?.items;
      setDisputeCount(Array.isArray(dItems) ? dItems.length : 0);
      const iItems = invoices.paypal?.items;
      setInvoiceCount(Array.isArray(iItems) ? iItems.length : 0);
      setSubscriptions(Array.isArray(subs.items) ? subs.items.length : 0);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [adminKey]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    let cancelled = false;
    void fetchCrewSupporterPlan()
      .then((body) => {
        if (!cancelled) setCrewPlanConfigured(Boolean(String(body.plan_id || "").trim()));
      })
      .catch(() => {
        if (!cancelled) setCrewPlanConfigured(null);
      });
    return () => {
      cancelled = true;
    };
  }, [setupNote]);

  const onSetup = async () => {
    const key = adminKey.trim();
    if (!key) return;
    setSetupNote(null);
    try {
      const body = await setupCrewSubscription(key);
      setSetupNote(body.idempotent ? t("treasurer.paypal.setupDone") : t("treasurer.paypal.setupCreated"));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  if (!adminKey.trim()) return null;

  return (
    <section className="panel treasurer-paypal" data-testid="treasurer-paypal-panel">
      <h3>{t("treasurer.paypal.heading")}</h3>
      <ul className="treasurer-paypal-list">
        <li data-testid="treasurer-dispute-count">
          {t("treasurer.paypal.disputes", { count: disputeCount ?? "—" })}
        </li>
        <li data-testid="treasurer-invoice-count">
          {t("treasurer.paypal.invoices", { count: invoiceCount ?? "—" })}
        </li>
        <li data-testid="treasurer-subscription-count">
          {t("treasurer.paypal.subscriptions", { count: subscriptions ?? "—" })}
        </li>
      </ul>
      {crewPlanConfigured === false ? (
        <p className="hint" data-testid="treasurer-crew-plan-missing-hint">
          {t("treasurer.paypal.crewPlanMissingHint")}
        </p>
      ) : null}
      <button type="button" data-testid="crew-subscription-setup" onClick={() => void onSetup()}>
        {t("treasurer.paypal.setupCrew")}
      </button>
      {setupNote ? <p className="notice">{setupNote}</p> : null}
      <p className="hint" data-testid="reconcile-lag-note">
        {t("treasurer.paypal.reconcileLag")}
      </p>
      {error ? <p className="notice error">{error}</p> : null}
    </section>
  );
}

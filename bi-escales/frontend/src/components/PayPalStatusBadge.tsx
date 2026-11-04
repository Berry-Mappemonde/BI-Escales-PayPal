import { useTranslation } from "react-i18next";
import type { PublicPledge } from "../api/types";

const STATUS_CLASS: Record<string, string> = {
  created: "pp-created",
  authorized: "pp-authorize",
  vaulted: "pp-vault",
  pending: "pp-pending",
  captured: "pp-captured",
  settled: "pp-settled",
  failed: "pp-failed",
  voided: "pp-voided",
};

export function PayPalStatusBadge({ pledge }: { pledge: PublicPledge }) {
  const { t } = useTranslation();
  const mode = pledge.payment_mode || pledge.intent || "AUTHORIZE";
  const tone = STATUS_CLASS[pledge.status] ?? "pp-unknown";
  return (
    <div className="paypal-status" data-testid={`paypal-badge-${pledge.id}`}>
      <span className="paypal-mark" aria-hidden>
        PP
      </span>
      <span className={`paypal-pill ${tone}`}>{pledge.status}</span>
      <span className="paypal-mode">{mode}</span>
      {pledge.authorization_id ? (
        <span className="paypal-meta" title={pledge.authorization_id}>
          {t("paypal.authShort")}: {pledge.authorization_id.slice(0, 12)}…
        </span>
      ) : null}
      {pledge.vault_id ? (
        <span className="paypal-meta" title={pledge.vault_id}>
          {t("paypal.vaultShort")}: {pledge.vault_id.slice(0, 12)}…
        </span>
      ) : null}
      {pledge.capture_id ? (
        <span className="paypal-meta" title={pledge.capture_id}>
          {t("paypal.captureShort")}: {pledge.capture_id.slice(0, 12)}…
        </span>
      ) : null}
      {pledge.paypal_status ? (
        <span className="paypal-meta">
          {t("paypal.paypalStatus")}: {pledge.paypal_status}
        </span>
      ) : null}
    </div>
  );
}

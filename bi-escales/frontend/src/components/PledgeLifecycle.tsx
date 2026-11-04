import { useTranslation } from "react-i18next";
import type { PublicPledge } from "../api/types";
import { PayPalStatusBadge } from "./PayPalStatusBadge";
import { formatMoney } from "../utils/money";

const KNOWN_STATUSES = [
  "created",
  "authorized",
  "vaulted",
  "pending",
  "captured",
  "settled",
  "failed",
  "voided",
] as const;

export function PledgeLifecycle({
  pledges,
  needsKey,
}: {
  pledges: PublicPledge[];
  needsKey?: boolean;
}) {
  const { t, i18n } = useTranslation();
  const seen = new Set(pledges.map((p) => p.status));

  return (
    <section className="panel pledge-lifecycle" data-testid="paypal-lifecycle">
      <h2>{t("lifecycle.heading")}</h2>
      <p className="hint">{t("lifecycle.hint")}</p>
      <p className="notice warn" data-testid="refund-absent">
        {t("lifecycle.refundAbsent")}
      </p>
      <ul className="state-legend">
        {KNOWN_STATUSES.map((status) => (
          <li key={status} data-known-status={status} className={seen.has(status) ? "seen" : "missing"}>
            {status}
          </li>
        ))}
      </ul>
      {needsKey ? (
        <p className="hint" data-testid="lifecycle-needs-key">
          {t("lifecycle.needsKey")}
        </p>
      ) : pledges.length === 0 ? (
        <p className="hint" data-testid="lifecycle-empty">
          {t("lifecycle.empty")}
        </p>
      ) : (
        <div className="lifecycle-list">
          {pledges.map((pledge) => (
            <article
              key={pledge.id}
              data-testid="lifecycle-row"
              data-status={pledge.status}
              data-paypal-status={pledge.paypal_status || ""}
            >
              <PayPalStatusBadge pledge={pledge} />
              <p>
                {formatMoney(pledge.amount_eur, i18n.language)} — {pledge.description}
              </p>
              <ol className="timeline">
                {(pledge.history && pledge.history.length > 0 ? pledge.history : [pledge.status]).map(
                  (step, index) => (
                    <li key={`${pledge.id}-${step}-${index}`}>{step}</li>
                  ),
                )}
              </ol>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

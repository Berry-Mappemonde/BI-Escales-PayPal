/**
 * Crew memberships for the treasurer (brief item B9): who is subscribed, and the
 * status of each subscription. Read-only: the rows come from the list the
 * treasurer panel already reads (GET /paypal/subscriptions, key only); nothing
 * here creates, changes or cancels a subscription.
 */
import { useTranslation } from "react-i18next";
import { formatPledgeCreatedAt, shortPledgeId } from "./TreasurerQueue";

export interface CrewMembershipRow {
  subscription_id: string;
  plan_id?: string | null;
  status?: string | null;
  subscriber_email?: string | null;
  at?: string | null;
  updated_at?: string | null;
}

/** PayPal's subscription states; anything else is shown as PayPal sent it. */
const KNOWN_STATUSES = ["ACTIVE", "APPROVAL_PENDING", "APPROVED", "SUSPENDED", "CANCELLED", "EXPIRED"];

/** Keeps the rows that are subscriptions, newest first. */
export function crewMembershipRows(items: unknown): CrewMembershipRow[] {
  if (!Array.isArray(items)) return [];
  const stamp = (row: CrewMembershipRow) => {
    const time = Date.parse(String(row.at || row.updated_at || ""));
    return Number.isFinite(time) ? time : 0;
  };
  return items
    .filter((item): item is CrewMembershipRow =>
      Boolean(item) && typeof item === "object" && Boolean(String((item as CrewMembershipRow).subscription_id || "").trim()))
    .slice()
    .sort((a, b) => stamp(b) - stamp(a) || String(a.subscription_id).localeCompare(String(b.subscription_id)));
}

export function TreasurerCrewMemberships({ items }: { items: unknown }) {
  const { t, i18n } = useTranslation();
  const rows = crewMembershipRows(items);
  const active = rows.filter((row) => String(row.status || "").toUpperCase() === "ACTIVE").length;
  const statusLabel = (raw: string | null | undefined) => {
    const status = String(raw || "").trim().toUpperCase();
    if (!status) return "—";
    return KNOWN_STATUSES.includes(status) ? t(`treasurer.paypal.crew.statuses.${status}`) : status;
  };

  return (
    <div className="treasurer-crew" data-testid="treasurer-crew-memberships">
      <h4>{t("treasurer.paypal.crew.heading")}</h4>
      {rows.length === 0 ? (
        <p className="hint" data-testid="treasurer-crew-empty">{t("treasurer.paypal.crew.empty")}</p>
      ) : (
        <>
          <p className="hint" data-testid="treasurer-crew-summary">
            {t("treasurer.paypal.crew.total", { count: rows.length })}
            {" · "}
            {t("treasurer.paypal.crew.active", { count: active })}
          </p>
          <div className="treasurer-crew-table">
            <table className="fallback-table">
              <thead>
                <tr>
                  <th scope="col">{t("treasurer.paypal.crew.member")}</th>
                  <th scope="col">{t("treasurer.paypal.crew.status")}</th>
                  <th scope="col">{t("treasurer.paypal.crew.since")}</th>
                  <th scope="col">{t("treasurer.paypal.crew.updated")}</th>
                  <th scope="col">{t("treasurer.paypal.crew.subscription")}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => {
                  const status = String(row.status || "").trim().toUpperCase();
                  return (
                    <tr key={row.subscription_id} data-testid={`crew-row-${row.subscription_id}`}>
                      <td>{String(row.subscriber_email || "").trim() || <span className="hint">{t("treasurer.paypal.crew.noEmail")}</span>}</td>
                      <td data-status={status || undefined}>{statusLabel(row.status)}</td>
                      <td>
                        <time dateTime={row.at || undefined}>{formatPledgeCreatedAt(row.at || undefined, i18n.language)}</time>
                      </td>
                      <td>
                        <time dateTime={row.updated_at || row.at || undefined}>
                          {formatPledgeCreatedAt(row.updated_at || row.at || undefined, i18n.language)}
                        </time>
                      </td>
                      <td>
                        <span className="treasurer-pledge-ref" title={row.subscription_id}>{shortPledgeId(row.subscription_id)}</span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
      <p className="hint">{t("treasurer.paypal.crew.readOnly")}</p>
    </div>
  );
}

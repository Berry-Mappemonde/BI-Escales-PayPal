/**
 * "Where the money goes": the public totals in one place (brief item A14).
 * Per stop, per cabin leg, per project and for the common fund, read from the
 * public GET /funds/public. Amounts only; nothing here starts a payment.
 *
 * Read when the visitor opens the disclosure, and again when `refreshToken`
 * changes while it is open (a pledge was just made).
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { fetchPublicFunds, type PublicFunds } from "../api/escales";
import { milestoneLabel } from "../utils/milestoneLabel";
import { formatEurAmount } from "../voyage/stopStatus.js";

export interface PublicTotalsProps {
  /** Milestone id -> stop name, from the voyage. */
  stopNames?: Record<string, string>;
  /** Project id -> title, when the project list knows it. */
  projectTitle?: (projectId: string) => string | undefined;
  /** Opens a stop's sheet; a stop row is a button only when this is given. */
  onSelectStop?: (milestoneId: string) => void;
  /** Change it to read the totals again while the list is open. */
  refreshToken?: number;
}

type State = { status: "idle" | "loading" | "error" } | { status: "ready"; funds: PublicFunds };

const positive = (value: unknown): number => {
  const amount = Number(value);
  return Number.isFinite(amount) && amount > 0 ? amount : 0;
};

export function PublicTotals({ stopNames, projectTitle, onSelectStop, refreshToken = 0 }: PublicTotalsProps) {
  const { t, i18n } = useTranslation();
  const lang = i18n.language?.startsWith("en") ? "en" : "fr";
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<State>({ status: "idle" });
  const request = useRef(0);

  const load = useCallback(() => {
    const mine = ++request.current;
    setState((current) => (current.status === "ready" ? current : { status: "loading" }));
    fetchPublicFunds()
      .then((funds) => {
        if (mine === request.current) setState({ status: "ready", funds });
      })
      .catch(() => {
        if (mine === request.current) setState({ status: "error" });
      });
  }, []);

  useEffect(() => {
    if (open) load();
  }, [open, refreshToken, load]);

  const money = (amount: number) => formatEurAmount(amount, lang);
  /** "€20 pledged", "€30 captured", "€5 refunded": one entry per amount that is not zero. */
  const amounts = (row: { authorized_eur?: string; captured_eur?: string; refunded_eur?: string }): string[] =>
    [
      positive(row.authorized_eur) ? t("publicTotals.pledged", { amount: money(positive(row.authorized_eur)) }) : null,
      positive(row.captured_eur) ? t("publicTotals.captured", { amount: money(positive(row.captured_eur)) }) : null,
      positive(row.refunded_eur) ? t("publicTotals.refunded", { amount: money(positive(row.refunded_eur)) }) : null,
    ].filter((part): part is string => Boolean(part));
  /** One amount per line; a middle dot between them for anyone reading the row as one sentence. */
  const amountLines = (parts: string[]) => (
    <span className="public-totals-amount">
      {parts.map((part, index) => (
        <span key={part}>
          {index ? <span className="visually-hidden"> · </span> : null}
          {part}
        </span>
      ))}
    </span>
  );

  const stopName = (row: { milestone_id: string; fund_id: string }) =>
    stopNames?.[row.milestone_id] ?? stopNames?.[`dep-${row.fund_id}`] ?? row.milestone_id;
  const stopId = (row: { milestone_id: string; fund_id: string }) =>
    stopNames?.[row.milestone_id] ? row.milestone_id : stopNames?.[`dep-${row.fund_id}`] ? `dep-${row.fund_id}` : null;
  const legName = (id: string) => milestoneLabel(stopNames, id, (_key, values) => t("publicTotals.leg", values));

  const funds = state.status === "ready" ? state.funds : null;
  const commonFund = funds ? amounts(funds.common_fund) : [];
  const empty = funds !== null && !funds.stops.length && !funds.legs.length && !funds.projects.length && !commonFund.length;

  return (
    <details
      className="panel project-disclosure public-totals"
      data-testid="public-totals"
      onToggle={(event) => setOpen((event.currentTarget as HTMLDetailsElement).open)}
    >
      <summary className="project-summary">
        <h2>{t("publicTotals.heading")}</h2>
        <svg viewBox="0 0 16 16" width="16" height="16" fill="none" aria-hidden="true"><path d="m5 6 3 3 3-3" stroke="currentColor" strokeWidth="1.5" /></svg>
      </summary>
      {state.status === "loading" ? <p className="hint" role="status" data-testid="public-totals-loading">{t("publicTotals.loading")}</p> : null}
      {state.status === "error" ? <p className="hint" role="status" data-testid="public-totals-error">{t("publicTotals.error")}</p> : null}
      {empty ? <p className="hint" data-testid="public-totals-empty">{t("publicTotals.empty")}</p> : null}
      {funds && !empty ? (
        <div className="public-totals-body" data-testid="public-totals-body">
          {funds.stops.length ? (
            <section data-testid="public-totals-stops">
              <h3>{t("publicTotals.stops")}</h3>
              <ul>
                {funds.stops.map((row) => {
                  const name = stopName(row);
                  const id = stopId(row);
                  return (
                    <li key={row.fund_id} data-testid={`public-total-${row.fund_id}`}>
                      {onSelectStop && id ? (
                        <button type="button" onClick={() => onSelectStop(id)} aria-label={t("publicTotals.openStop", { name })}>
                          {name}
                        </button>
                      ) : (
                        <span>{name}</span>
                      )}
                      {amountLines(amounts(row))}
                    </li>
                  );
                })}
              </ul>
            </section>
          ) : null}
          {funds.legs.length ? (
            <section data-testid="public-totals-legs">
              <h3>{t("publicTotals.cabins")}</h3>
              <ul>
                {funds.legs.map((row) => (
                  <li key={row.fund_id} data-testid={`public-total-${row.fund_id}`}>
                    <span title={row.fund_id}>{legName(row.fund_id)}</span>
                    {amountLines(amounts(row))}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
          {funds.projects.length ? (
            <section data-testid="public-totals-projects">
              <h3>{t("publicTotals.projects")}</h3>
              <ul>
                {funds.projects.map((row) => (
                  <li key={row.project_id} data-testid={`public-total-project-${row.project_id}`}>
                    <span title={row.project_id}>{projectTitle?.(row.project_id) || row.project_id}</span>
                    {amountLines(
                      [
                        positive(row.amount_eur) ? t("publicTotals.captured", { amount: money(positive(row.amount_eur)) }) : null,
                        row.donation_count ? t("publicTotals.donations", { count: row.donation_count }) : null,
                      ].filter((part): part is string => Boolean(part)),
                    )}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
          <section data-testid="public-totals-common-fund">
            <h3>{t("publicTotals.commonFund")}</h3>
            <ul>
              <li>
                <span>{t("publicTotals.commonFundRow")}</span>
                {amountLines(commonFund.length ? commonFund : [t("publicTotals.nothing")])}
              </li>
            </ul>
          </section>
          <p className="hint public-totals-note">{t("publicTotals.note")}</p>
        </div>
      ) : null}
    </details>
  );
}

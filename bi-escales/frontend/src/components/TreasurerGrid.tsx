import { useEffect, useMemo, useState, type ComponentType } from "react";
import { useTranslation } from "react-i18next";
import type { Milestone, PublicPledge } from "../api/types";
import { featureAgGridEnabled } from "../config/features";
import { buildGaugeRows, buildMarinaDashboardRows, gaugePercent } from "../utils/gauges";

type AgTableProps = { rows: ReturnType<typeof buildGaugeRows> };

function OptionalAgGrid({ rows }: AgTableProps) {
  const [Table, setTable] = useState<ComponentType<AgTableProps> | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    // Build-time checks let Vite omit this optional chunk when disabled.
    if (!(import.meta.env.VITE_ENABLE_AG_GRID === "1"
      || import.meta.env.VITE_ENABLE_AG_GRID === "true"
      || import.meta.env.VITE_ENABLE_AG_GRID === "yes"
      || import.meta.env.VITE_ENABLE_AG_GRID === "on")) return;
    import("./TreasurerGridAg")
      .then((mod: { default?: ComponentType<AgTableProps> }) => {
        if (!cancelled && mod.default) setTable(() => mod.default as ComponentType<AgTableProps>);
        else if (!cancelled) setFailed(true);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (failed || !Table) return <FallbackTreasurerTable rows={rows} />;
  return <Table rows={rows} />;
}

export interface TreasurerGridProps {
  pledges: PublicPledge[];
  milestones: Milestone[];
  adminKey: string;
  onMilestonesChange: (milestones: Milestone[]) => void;
  onPledgeUpdated: (pledge: PublicPledge) => void;
  selectedMilestoneId: string;
  onSelectMilestone: (id: string) => void;
}

function GaugeBar({ label, percent, tone }: { label: string; percent: number; tone: string }) {
  return (
    <div className="gauge">
      <div className="gauge-label">
        <span>{label}</span>
        <span>{percent}%</span>
      </div>
      <div className="gauge-track">
        <div className={`gauge-fill ${tone}`} style={{ width: `${percent}%` }} />
      </div>
    </div>
  );
}

function FallbackTreasurerTable({ rows }: { rows: ReturnType<typeof buildGaugeRows> }) {
  const { t } = useTranslation();
  return (
    <table className="fallback-table grid-table" data-testid="treasurer-fallback-table">
      <thead>
        <tr>
          <th>{t("grid.milestone")}</th>
          <th>{t("grid.authorized")}</th>
          <th>{t("grid.captured")}</th>
          <th>{t("grid.voided")}</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.milestone_id}>
            <td>{row.milestone_id}</td>
            <td>
              {row.authorized_count} ({row.authorized_total_eur.toFixed(2)} €)
              <GaugeBar
                label={t("grid.authorized")}
                percent={gaugePercent(row, "authorized")}
                tone="tone-auth"
              />
            </td>
            <td>
              {row.captured_count} ({row.captured_total_eur.toFixed(2)} €)
              <GaugeBar
                label={t("grid.captured")}
                percent={gaugePercent(row, "captured")}
                tone="tone-cap"
              />
            </td>
            <td>
              {row.voided_count}
              <GaugeBar label={t("grid.voided")} percent={gaugePercent(row, "voided")} tone="tone-void" />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function TreasurerGrid(props: TreasurerGridProps) {
  const { t } = useTranslation();
  const rows = useMemo(() => buildGaugeRows(props.pledges), [props.pledges]);
  const marinaRows = useMemo(() => buildMarinaDashboardRows(props.pledges), [props.pledges]);
  const agGrid = featureAgGridEnabled();

  return (
    <>
    <section className="panel treasurer-grid">
      <h3>{t("grid.heading")}</h3>
      {agGrid ? <OptionalAgGrid rows={rows} /> : <FallbackTreasurerTable rows={rows} />}
    </section>
    <section className="panel treasurer-marina-grid" data-testid="treasurer-marina-dashboard">
      <h3>{t("grid.marinaHeading")}</h3>
      {marinaRows.some((row) => row.marina_payout_status !== "—") ? (
        <p className="hint" data-testid="marina-payout-banner">
          {t("grid.marinaPayoutBanner")}
        </p>
      ) : null}
      {marinaRows.length === 0 ? (
        <p className="hint">{t("grid.marinaEmpty")}</p>
      ) : (
        <table className="fallback-table grid-table" data-testid="marina-dashboard-table">
          <thead>
            <tr>
              <th>{t("grid.marinaStop")}</th>
              <th>{t("grid.marinaBookings")}</th>
              <th>{t("grid.marinaGross")}</th>
              <th>
                {marinaRows.some((row) => row.fees_simulated)
                  ? t("grid.marinaFeesSimulated")
                  : t("grid.marinaFees")}
              </th>
              <th>
                {marinaRows.some((row) => row.fees_simulated)
                  ? t("grid.marinaNetSimulated")
                  : t("grid.marinaNet")}
              </th>
              <th>{t("grid.marinaPayoutStatus")}</th>
              <th>{t("grid.marinaRefunds")}</th>
              <th>{t("grid.marinaDisputes")}</th>
            </tr>
          </thead>
          <tbody>
            {marinaRows.map((row) => (
              <tr key={row.marina_key}>
                <td>{row.marina_key}</td>
                <td>{row.berth_bookings}</td>
                <td>{row.gross_eur.toFixed(2)} €</td>
                <td>{row.platform_fees_eur.toFixed(2)} €</td>
                <td>{row.marina_net_eur.toFixed(2)} €</td>
                <td data-testid={`marina-payout-status-${row.marina_key}`}>
                  {row.marina_payout_status === "—"
                    ? "—"
                    : t(`grid.marinaPayoutStatus.${row.marina_payout_status}`, {
                        defaultValue: row.marina_payout_status,
                      })}
                </td>
                <td>{row.refunds_eur.toFixed(2)} €</td>
                <td>{row.disputes_open}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
    </>
  );
}

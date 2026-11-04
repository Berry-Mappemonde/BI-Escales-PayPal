import { useEffect, useMemo, useState, type ComponentType } from "react";
import { useTranslation } from "react-i18next";
import type { Milestone, PublicPledge } from "../api/types";
import { featureAgGridEnabled } from "../config/features";
import { buildGaugeRows, gaugePercent } from "../utils/gauges";

type AgTableProps = { rows: ReturnType<typeof buildGaugeRows> };

function OptionalAgGrid({ rows }: AgTableProps) {
  const [Table, setTable] = useState<ComponentType<AgTableProps> | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    // Variable specifier so the core Vite/tsc build does not import ag-grid.
    // ag-grid-community is not AG Studio and is not a prize claim.
    const specifier = "./TreasurerGridAg.tsx";
    import(/* @vite-ignore */ specifier)
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
  const agGrid = featureAgGridEnabled();

  return (
    <section className="panel treasurer-grid">
      <h2>{t("grid.heading")}</h2>
      {agGrid ? <OptionalAgGrid rows={rows} /> : <FallbackTreasurerTable rows={rows} />}
    </section>
  );
}

import { lazy, Suspense, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { captainReview, capturePledge, voidPledge } from "../api/escales";
import type { CaptainProposal, Milestone, PublicPledge } from "../api/types";
import { featureAgGridEnabled } from "../config/features";
import { buildGaugeRows, gaugePercent } from "../utils/gauges";

const AgGridTreasurerTable = lazy(() => import("./TreasurerGridAg"));

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

export function CaptainProposalWidget({
  milestoneId,
  milestones,
  adminKey,
  onProposal,
  onPledgeUpdated,
}: {
  milestoneId: string;
  milestones: Milestone[];
  adminKey: string;
  onProposal: (p: CaptainProposal) => void;
  onPledgeUpdated: (p: PublicPledge) => void;
}) {
  const { t } = useTranslation();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const stored = milestones.find((m) => m.id === milestoneId)?.proposal ?? null;

  const requestReview = async () => {
    setLoading(true);
    setError(null);
    try {
      const proposal = await captainReview(milestoneId);
      onProposal(proposal);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const applyProposal = async (action: "capture" | "void") => {
    if (!stored?.pledge_ids?.length) return;
    if (!adminKey.trim()) {
      setError("Admin key required");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      for (const id of stored.pledge_ids) {
        const updated =
          action === "capture"
            ? await capturePledge(id, adminKey.trim())
            : await voidPledge(id, adminKey.trim());
        onPledgeUpdated(updated);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const proposalLabel =
    stored?.proposal === "capture"
      ? t("grid.proposalCapture")
      : stored?.proposal === "void"
        ? t("grid.proposalVoid")
        : stored?.proposal === "wait"
          ? t("grid.proposalWait")
          : t("grid.noProposal");

  return (
    <div className="captain-widget" data-testid="captain-proposal-widget">
      <h3>{t("grid.captainProposal")}</h3>
      <p className="hint">{t("grid.humanValidation")}</p>
      <label>
        {t("escales.milestoneId")}
        <input value={milestoneId} readOnly />
      </label>
      <button type="button" onClick={() => void requestReview()} disabled={loading}>
        {t("grid.requestReview")}
      </button>
      {error ? <p className="notice error">{error}</p> : null}
      {stored ? (
        <div className="proposal-box">
          <p>
            <strong>{proposalLabel}</strong>
          </p>
          {stored.justification ? <p>{stored.justification}</p> : null}
          <p>IDs: {stored.pledge_ids.join(", ") || "—"}</p>
          {stored.proposal === "capture" ? (
            <button type="button" disabled={busy} onClick={() => void applyProposal("capture")}>
              {t("grid.applyCapture")}
            </button>
          ) : null}
          {stored.proposal === "void" ? (
            <button type="button" disabled={busy} onClick={() => void applyProposal("void")}>
              {t("grid.applyVoid")}
            </button>
          ) : null}
        </div>
      ) : (
        <p className="hint">{t("grid.noProposal")}</p>
      )}
    </div>
  );
}

export function TreasurerGrid(props: TreasurerGridProps) {
  const { t } = useTranslation();
  const rows = useMemo(() => buildGaugeRows(props.pledges), [props.pledges]);
  const agGrid = featureAgGridEnabled();

  const mergeProposal = (proposal: CaptainProposal) => {
    props.onMilestonesChange(
      props.milestones.some((m) => m.id === proposal.milestone_id)
        ? props.milestones.map((m) =>
            m.id === proposal.milestone_id ? { ...m, proposal } : m,
          )
        : [...props.milestones, { id: proposal.milestone_id, evidence: [], proposal }],
    );
  };

  return (
    <section className="panel treasurer-grid">
      <h2>{t("grid.heading")}</h2>
      {!agGrid ? <p className="hint">{t("grid.agGridOff")}</p> : null}
      {agGrid ? (
        <Suspense fallback={<FallbackTreasurerTable rows={rows} />}>
          <AgGridTreasurerTable rows={rows} />
        </Suspense>
      ) : (
        <FallbackTreasurerTable rows={rows} />
      )}
      <CaptainProposalWidget
        milestoneId={props.selectedMilestoneId}
        milestones={props.milestones}
        adminKey={props.adminKey}
        onProposal={mergeProposal}
        onPledgeUpdated={props.onPledgeUpdated}
      />
    </section>
  );
}

import { FormEvent, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import type { FundView, PublicPledge } from "../api/types";
import { MaskedSecretInput } from "./MaskedSecretInput";
import { TreasurerPayPalPanel } from "./TreasurerPayPalPanel";
import { TreasurerWebhookPanel } from "./TreasurerWebhookPanel";
import { TreasurerQueue } from "./TreasurerQueue";
import { TreasurerGrid } from "./TreasurerGrid";
import { TreasurerStudioSection } from "./TreasurerStudioSection";
import { DemoStopMoment } from "./DemoStopMoment";
import "./treasurer-panel.css";

function OpenFundTotals({
  title,
  fund,
  testId,
}: {
  title: string;
  fund: FundView | null | undefined;
  testId: string;
}) {
  const { t } = useTranslation();
  const figures = fund
    ? t("fund.figures", {
        balance: fund.balance_eur,
        currency: fund.currency,
        income: fund.income_eur,
        spending: fund.spending_eur,
      })
    : fund === null
      ? t("fund.missing")
      : "";
  return (
    <p data-testid={testId}>
      {title}
      {figures ? ` — ${figures}` : ""}
    </p>
  );
}

export interface TreasurerPanelProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  adminKey: string;
  onAdminKeyChange: (value: string) => void;
  settleBusy: boolean;
  settleNote: string | null;
  onSettle: () => void;
  clockPinned: boolean;
  settleAt: string;
  onSettleAtChange: (value: string) => void;
  onSettleAt: () => void;
  milestoneId: string;
  onMilestoneIdChange: (value: string) => void;
  projectFund: FundView | null | undefined;
  boatFund: FundView | null | undefined;
  pledges: PublicPledge[];
  loading: boolean;
  error: string | null;
  needsKey: boolean;
  onRefreshQueue: () => void;
  onPledgeUpdated: (pledge: PublicPledge) => void;
  spendAmount: string;
  onSpendAmountChange: (value: string) => void;
  spendNote: string;
  onSpendNoteChange: (value: string) => void;
  spendError: string | null;
  fund: FundView | null;
  onSpendSubmit: (event: FormEvent) => void;
  demoMode?: boolean;
  children?: ReactNode;
}

export function TreasurerPanel({
  open,
  onOpenChange,
  adminKey,
  onAdminKeyChange,
  settleBusy,
  settleNote,
  onSettle,
  clockPinned,
  settleAt,
  onSettleAtChange,
  onSettleAt,
  milestoneId,
  onMilestoneIdChange: _onMilestoneIdChange,
  projectFund,
  boatFund,
  pledges,
  loading,
  error,
  needsKey,
  onRefreshQueue,
  onPledgeUpdated,
  spendAmount,
  onSpendAmountChange,
  spendNote,
  onSpendNoteChange,
  spendError,
  fund,
  onSpendSubmit,
  demoMode = false,
  children,
}: TreasurerPanelProps) {
  const { t } = useTranslation();

  return (
    <section className="treasurer-panel panel" data-testid="treasurer-panel">
      <header className="treasurer-panel-heading">
        <h2>
          <button
            type="button"
            className="treasurer-panel-toggle"
            data-testid="treasurer-panel-toggle"
            aria-expanded={open}
            aria-controls="treasurer-panel-body"
            onClick={() => onOpenChange(!open)}
          >
            {t("treasurer.panelTitle")}
          </button>
        </h2>
        {children}
      </header>
      {open ? (
        <div className="treasurer-panel-body" id="treasurer-panel-body" data-testid="treasurer-panel-body">
          {demoMode ? (
            <>
            <p className="notice demo-treasurer-banner" data-testid="demo-treasurer-banner">
              {t("treasurer.demoBanner")}
            </p>
            <DemoStopMoment onRefresh={onRefreshQueue} />
            </>
          ) : (
            <>
          <p className="hint">{t("treasurer.adminKeyHint")}</p>
          <MaskedSecretInput
            className="admin-key shared-admin"
            label={t("treasurer.adminKey")}
            value={adminKey}
            onChange={onAdminKeyChange}
            testId="admin-key-input"
            autoComplete="off"
          />
          <p className="hint" data-testid="treasurer-milestone-hint">
            {t("treasurer.milestoneFromStop", { id: milestoneId.trim() || "—" })}
          </p>
          <button
            type="button"
            data-testid="departure-settle"
            disabled={!adminKey.trim() || settleBusy}
            onClick={() => onSettle()}
          >
            {t("treasurer.settle")}
          </button>
          {settleNote ? (
            <p className="notice treasurer-settle-note" data-testid="settle-note">
              {settleNote.split("\n").map((line, index) => (
                <span key={`${index}-${line}`} className="settle-note-line">
                  {line}
                  {index < settleNote.split("\n").length - 1 ? <br /> : null}
                </span>
              ))}
            </p>
          ) : null}
          {clockPinned ? (
            <div className="stack-form" data-testid="settle-at-chosen">
              <label>
                {t("treasurer.settleAtLabel")}
                <input
                  type="datetime-local"
                  value={settleAt}
                  onChange={(event) => onSettleAtChange(event.target.value)}
                  data-testid="settle-at-input"
                />
              </label>
              <button
                type="button"
                data-testid="settle-at-chosen-button"
                disabled={!adminKey.trim() || !settleAt.trim() || settleBusy}
                onClick={() => onSettleAt()}
              >
                {t("treasurer.settleAtButton")}
              </button>
            </div>
          ) : null}
          <section className="panel" data-testid="treasurer-open-funds">
            <h2>{t("fund.openHeading")}</h2>
            <OpenFundTotals title={t("fund.projectTotals")} fund={projectFund} testId="project-fund-totals" />
            <OpenFundTotals title={t("fund.boatTotals")} fund={boatFund} testId="common-fund-totals" />
          </section>
            </>
          )}
          <TreasurerQueue
            pledges={pledges}
            loading={loading}
            error={error}
            needsKey={needsKey}
            adminKey={adminKey}
            demoTreasurer={demoMode}
            onRefresh={onRefreshQueue}
            onUpdated={onPledgeUpdated}
          />
          {!demoMode ? (
            <>
          <TreasurerPayPalPanel adminKey={adminKey} />
          <TreasurerWebhookPanel adminKey={adminKey} />
          <TreasurerGrid
            pledges={pledges}
            milestones={[]}
            adminKey={adminKey}
            selectedMilestoneId={milestoneId}
            onSelectMilestone={_onMilestoneIdChange}
            onMilestonesChange={() => {}}
            onPledgeUpdated={onPledgeUpdated}
          />
          <TreasurerStudioSection pledges={pledges} />
          <form className="stack-form" onSubmit={onSpendSubmit}>
            <h2>{t("fund.heading")}</h2>
            <label>
              {t("fund.spendAmount")}
              <input value={spendAmount} onChange={(event) => onSpendAmountChange(event.target.value)} />
            </label>
            <label>
              {t("fund.spendDescription")}
              <input value={spendNote} onChange={(event) => onSpendNoteChange(event.target.value)} />
            </label>
            <button type="submit" disabled={!adminKey.trim() || !milestoneId || !spendNote.trim()}>
              {t("fund.spendSubmit")}
            </button>
            {spendError ? <p className="notice error">{spendError}</p> : null}
            {fund ? (
              <p data-testid="common-fund">
                {t("fund.figures", {
                  balance: fund.balance_eur,
                  currency: fund.currency,
                  income: fund.income_eur,
                  spending: fund.spending_eur,
                })}
              </p>
            ) : null}
          </form>
            </>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

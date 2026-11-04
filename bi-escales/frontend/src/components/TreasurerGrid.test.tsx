import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import { TreasurerGrid } from "../components/TreasurerGrid";

function wrap(ui: ReactNode) {
  return render(<I18nextProvider i18n={i18n}>{ui}</I18nextProvider>);
}

describe("TreasurerGrid fallback", () => {
  it("affiche le tableau HTML quand AG Grid est désactivé", () => {
    vi.stubEnv("VITE_ENABLE_AG_GRID", "0");
    wrap(
      <TreasurerGrid
        pledges={[
          {
            id: "p1",
            status: "authorized",
            intent: "AUTHORIZE",
            currency: "EUR",
            amount_eur: "10.00",
            description: "test",
            milestone_id: "dep-mayotte",
          },
        ]}
        milestones={[]}
        adminKey=""
        selectedMilestoneId="dep-mayotte"
        onSelectMilestone={() => {}}
        onMilestonesChange={() => {}}
        onPledgeUpdated={() => {}}
      />,
    );
    expect(screen.getByTestId("treasurer-fallback-table")).toBeInTheDocument();
    expect(screen.queryByTestId("treasurer-ag-grid")).toBeNull();
    expect(screen.getByTestId("captain-proposal-widget")).toBeInTheDocument();
  });
});

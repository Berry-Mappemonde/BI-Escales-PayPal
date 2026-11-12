import type { ReactNode } from "react";
import { render, screen, within } from "@testing-library/react";
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
    expect(screen.queryByRole("button", { name: /avis du capitaine|captain review/i })).toBeNull();
  });

  it("names the stop in the Milestone column, and falls back to the id", async () => {
    await i18n.changeLanguage("en");
    vi.stubEnv("VITE_ENABLE_AG_GRID", "0");
    const hold = (id: string, milestone_id: string) => ({
      id,
      status: "authorized" as const,
      intent: "AUTHORIZE",
      currency: "EUR",
      amount_eur: "10.00",
      description: "test",
      milestone_id,
    });
    wrap(
      <TreasurerGrid
        pledges={[hold("p1", "dep-mayotte"), hold("p2", "leg-unknown"), hold("p3", "leg-mayotte-to-la-reunion")]}
        milestones={[]}
        adminKey=""
        selectedMilestoneId="dep-mayotte"
        onSelectMilestone={() => {}}
        onMilestonesChange={() => {}}
        onPledgeUpdated={() => {}}
        stopNames={{ "dep-mayotte": "Mamoudzou (Mayotte)", "dep-la-reunion": "Le Port (La Réunion)" }}
      />,
    );
    const table = screen.getByTestId("treasurer-fallback-table");
    const named = within(table).getByRole("cell", { name: "Mamoudzou (Mayotte)" });
    expect(named).toHaveAttribute("title", "dep-mayotte");
    expect(within(table).queryByText("dep-mayotte")).toBeNull();
    expect(within(table).getByRole("cell", { name: "leg-unknown" })).toBeInTheDocument();
    const cabin = within(table).getByRole("cell", { name: "Cabin: Mamoudzou (Mayotte) → Le Port (La Réunion)" });
    expect(cabin).toHaveAttribute("title", "leg-mayotte-to-la-reunion");
  });

  it.each([
    ["en", "Stop"],
    ["fr", "Escale"],
  ])("heads the stop column with the same word in %s", async (lang, word) => {
    await i18n.changeLanguage(lang);
    vi.stubEnv("VITE_ENABLE_AG_GRID", "0");
    wrap(
      <TreasurerGrid
        pledges={[]}
        milestones={[]}
        adminKey=""
        selectedMilestoneId="dep-mayotte"
        onSelectMilestone={() => {}}
        onMilestonesChange={() => {}}
        onPledgeUpdated={() => {}}
      />,
    );
    const table = screen.getByTestId("treasurer-fallback-table");
    expect(within(table).getByRole("columnheader", { name: word })).toBeInTheDocument();
    await i18n.changeLanguage("en");
  });
  it.each([
    ["en", "Stop gift (held until arrival)"],
    ["fr", "Don d’escale (retenu jusqu’à l’arrivée)"],
  ])("lists a stop's gifts on a line of their own in %s", async (lang, label) => {
    await i18n.changeLanguage(lang);
    vi.stubEnv("VITE_ENABLE_AG_GRID", "0");
    const base = { intent: "AUTHORIZE", currency: "EUR", description: "x", milestone_id: "dep-mayotte" };
    wrap(
      <TreasurerGrid
        pledges={[
          { ...base, id: "m1", status: "captured" as const, amount_eur: "20.00", kind: "mile" },
          { ...base, id: "g1", status: "authorized" as const, amount_eur: "17.35", kind: "stop_gift" },
        ]}
        milestones={[]}
        adminKey=""
        selectedMilestoneId="dep-mayotte"
        onSelectMilestone={() => {}}
        onMilestonesChange={() => {}}
        onPledgeUpdated={() => {}}
        stopNames={{ "dep-mayotte": "Mamoudzou (Mayotte)" }}
      />,
    );
    const table = screen.getByTestId("treasurer-fallback-table");
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
    expect(rows[0]).not.toHaveTextContent(label);
    const gift = screen.getByTestId("ledger-stop-gift-row");
    expect(gift).toBe(rows[1]);
    expect(within(gift).getAllByRole("cell")[0]).toHaveTextContent(`Mamoudzou (Mayotte)${label}`);
    expect(gift).toHaveTextContent("1 (17.35 €)");
    await i18n.changeLanguage("en");
  });
});

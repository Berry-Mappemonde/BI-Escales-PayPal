/**
 * Mini-mix lot 2 — button cleanup (plan canvas P2 remaining lots, 18-row inventory).
 * Source: Escales mini-mix plan Page, section “Buttons and sign-ups inventory”.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { describe, expect, it, vi } from "vitest";
import i18n from "./i18n";
import EscalesScheduler from "./components/escales/EscalesScheduler.jsx";
import { TreasurerPanel } from "./components/TreasurerPanel";
import { TreasurerQueue } from "./components/TreasurerQueue";
import type { PublicPledge } from "./api/types";

const schedule = {
  escales: [
    { milestone_id: "dep-la-rochelle", name: "La Rochelle", arrival_iso: "2026-11-12T12:00:00Z" },
  ],
  legs: [
    {
      id: "leg-la-rochelle-to-ajaccio-corse",
      from_name: "La Rochelle",
      to_name: "Ajaccio (Corse)",
      departure_iso: "2026-11-12T12:00:00Z",
    },
  ],
  prices: { prices: [{ kind: "cabin_leg", amount_eur: "80.00", currency: "EUR" }] },
};

vi.mock("./components/PledgeButton", () => ({
  PledgeButton: () => <button type="button">pledge</button>,
}));

describe("minimix lot 2 removed controls", () => {
  it("does not render the treasurer milestone text field (stop selection drives the milestone)", async () => {
    await i18n.changeLanguage("en");
    render(
      <I18nextProvider i18n={i18n}>
        <TreasurerPanel
          open
          onOpenChange={() => {}}
          adminKey="tk"
          onAdminKeyChange={() => {}}
          settleBusy={false}
          settleNote={null}
          onSettle={() => {}}
          clockPinned={false}
          settleAt=""
          onSettleAtChange={() => {}}
          onSettleAt={() => {}}
          milestoneId="dep-mayotte"
          onMilestoneIdChange={() => {}}
          projectFund={undefined}
          boatFund={undefined}
          pledges={[]}
          loading={false}
          error={null}
          needsKey
          onRefreshQueue={() => {}}
          onPledgeUpdated={() => {}}
          spendAmount="1.00"
          onSpendAmountChange={() => {}}
          spendNote=""
          onSpendNoteChange={() => {}}
          spendError={null}
          fund={null}
          onSpendSubmit={(event) => event.preventDefault()}
        />
      </I18nextProvider>,
    );
    expect(screen.queryByRole("textbox", { name: /milestone/i })).toBeNull();
    expect(screen.getByTestId("treasurer-milestone-hint")).toHaveTextContent("dep-mayotte");
  });

  it("drops the duplicate treasurer admin-key hint above the queue refresh button", async () => {
    await i18n.changeLanguage("en");
    const pledge: PublicPledge = {
      id: "p-1",
      status: "authorized",
      intent: "AUTHORIZE",
      amount_eur: "20.00",
      currency: "EUR",
      description: "miles",
      milestone_id: "dep-la-rochelle",
    };
    render(
      <I18nextProvider i18n={i18n}>
        <TreasurerQueue
          pledges={[pledge]}
          adminKey="key"
          onRefresh={() => {}}
          onUpdated={() => {}}
        />
      </I18nextProvider>,
    );
    expect(screen.queryByText(/Held in memory only/i)).toBeNull();
    expect(screen.getByRole("button", { name: /Refresh queue/i })).toBeInTheDocument();
  });

  it("hides scheduler planning buttons when Bryntum is off", () => {
    const { container } = render(
      <I18nextProvider i18n={i18n}>
        <EscalesScheduler
          schedule={schedule}
          planningEnabled={false}
          onSelectEscale={() => {}}
          onAuthorized={() => {}}
        />
      </I18nextProvider>,
    );
    expect(container.firstChild).toBeNull();
    expect(screen.queryByTestId("schedule-leg")).toBeNull();
    expect(screen.queryByRole("button", { name: "pledge" })).toBeNull();
  });

  it("shows scheduler leg pledge controls when Bryntum is on", () => {
    render(
      <I18nextProvider i18n={i18n}>
        <EscalesScheduler
          schedule={schedule}
          planningEnabled
          onSelectEscale={() => {}}
          onAuthorized={() => {}}
        />
      </I18nextProvider>,
    );
    // Still offered when Bryntum is on, one step away: behind "Book a cabin on a leg".
    expect(screen.queryByTestId("schedule-leg")).toBeNull();
    const cabins = screen.getByTestId("schedule-cabins") as HTMLDetailsElement;
    cabins.open = true;
    fireEvent(cabins, new Event("toggle"));
    expect(screen.getByTestId("schedule-leg")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "pledge" })).toBeInTheDocument();
  });
});

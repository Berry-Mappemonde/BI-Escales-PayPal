/**
 * Issue #145: in the demo treasurer view, the pledges this browser made get a "Yours" tag
 * and live buttons; every other pledge stays view-only. With the treasurer key the page is
 * the keyed one, unchanged.
 */
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { demoPlay, fetchOwnDemoPledges, type DemoPlay } from "../api/demoPlay";
import { captainReview, capturePledge, refundPledge, voidPledge } from "../api/escales";
import i18n from "../i18n";
import { TreasurerPanel } from "./TreasurerPanel";
import { TreasurerQueue } from "./TreasurerQueue";

vi.mock("../api/escales", async (load) => ({
  ...(await load<typeof import("../api/escales")>()),
  approveCaptainReview: vi.fn(),
  captainReview: vi.fn(),
  capturePledge: vi.fn(),
  fetchSchedule: vi.fn().mockResolvedValue({}),
  refundPledge: vi.fn(),
  voidPledge: vi.fn(),
  fetchFeatures: vi.fn().mockResolvedValue({}),
}));
vi.mock("../api/demoPlay", () => ({ demoPlay: vi.fn(), fetchOwnDemoPledges: vi.fn() }));

const row = (id: string, status = "authorized") => ({
  id, status, intent: "AUTHORIZE", currency: "EUR", amount_eur: "20.00", description: "", milestone_id: "dep-la-rochelle", created_at: "2026-11-11T10:00:00Z",
}) as never;
const play = (id: string, actions: DemoPlay["actions"], status = "authorized"): DemoPlay => ({
  pledge_id: id, status, arrival_simulated_at: null, approved_at: null, actions,
});
const stopNames = { "dep-la-rochelle": "La Rochelle" };

function show(props: Partial<React.ComponentProps<typeof TreasurerQueue>> = {}) {
  const onRefresh = vi.fn();
  const onUpdated = vi.fn();
  render(
    <I18nextProvider i18n={i18n}>
      <TreasurerQueue pledges={[row("mine-0001"), row("theirs-0002")]} adminKey="" demoTreasurer stopNames={stopNames} onRefresh={onRefresh} onUpdated={onUpdated} {...props} />
    </I18nextProvider>,
  );
  return { onRefresh, onUpdated };
}

describe("demo treasurer: a visitor's own pledges", () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    await i18n.changeLanguage("en");
    vi.mocked(captainReview).mockResolvedValue({ milestone_id: "dep-la-rochelle", proposal: "wait", pledge_ids: [] });
    vi.mocked(fetchOwnDemoPledges).mockResolvedValue([play("mine-0001", ["simulate_arrival", "void"])]);
  });
  afterEach(() => vi.clearAllMocks());

  it("tags the visitor's own pledge and gives it live buttons; the other stays view-only", async () => {
    show();
    const mine = within(await screen.findByTestId("own-actions-mine-0001"));
    expect(screen.getByTestId("own-tag-mine-0001")).toHaveTextContent("Yours");
    expect(mine.getByRole("button", { name: "Simulate arrival" })).toBeEnabled();
    expect(mine.getByRole("button", { name: "Void" })).toBeEnabled();
    expect(screen.getByTestId("own-step-mine-0001")).toHaveTextContent("Held in PayPal. Next: the boat arrives, for this pledge only.");

    const theirs = screen.getByTestId("queue-row-theirs-0002");
    expect(within(theirs).queryByTestId("own-tag-theirs-0002")).toBeNull();
    expect(within(theirs).queryByTestId("own-actions-theirs-0002")).toBeNull();
    expect(within(theirs).queryByRole("button", { name: /Simulate arrival|Approve|Capture|Void|Refund/ })).toBeNull();
    expect(screen.getByTestId("treasurer-demo-readonly")).toHaveTextContent("Only the browser that made a pledge can act on it here.");
  });

  it("walks the pledge through arrival, approval and capture, one step at a time", async () => {
    const { onRefresh, onUpdated } = show();
    vi.mocked(demoPlay)
      .mockResolvedValueOnce({ pledge: row("mine-0001"), play: { ...play("mine-0001", ["approve", "void"]), arrival_simulated_at: "2026-11-12T12:00:00+00:00" } })
      .mockResolvedValueOnce({ pledge: row("mine-0001"), play: { ...play("mine-0001", ["capture", "void"]), approved_at: "now" } })
      .mockResolvedValueOnce({ pledge: row("mine-0001", "captured"), play: play("mine-0001", ["refund"], "captured") });

    fireEvent.click(await screen.findByTestId("own-simulate_arrival-mine-0001"));
    await screen.findByTestId("own-approve-mine-0001");
    expect(screen.getByTestId("own-step-mine-0001")).toHaveTextContent("The boat has arrived, for this pledge only.");
    expect(screen.getByTestId("demo-play-note")).toHaveTextContent("Pledge mine-000: arrival simulated, for this pledge only.");
    expect(screen.queryByTestId("own-capture-mine-0001")).toBeNull();

    fireEvent.click(screen.getByTestId("own-approve-mine-0001"));
    await screen.findByTestId("own-capture-mine-0001");
    expect(screen.getByTestId("own-step-mine-0001")).toHaveTextContent("Approved by you. Next: capture, or void instead.");

    fireEvent.click(screen.getByTestId("own-capture-mine-0001"));
    await screen.findByTestId("own-refund-mine-0001");
    expect(screen.getByTestId("demo-play-note")).toHaveTextContent("captured in the PayPal sandbox");
    expect(vi.mocked(demoPlay).mock.calls).toEqual([["mine-0001", "simulate_arrival"], ["mine-0001", "approve"], ["mine-0001", "capture"]]);
    expect(onUpdated).toHaveBeenCalledTimes(3);
    expect(onRefresh).toHaveBeenCalledTimes(3);
    // The treasurer's keyed calls were never used.
    expect(capturePledge).not.toHaveBeenCalled();
    expect(voidPledge).not.toHaveBeenCalled();
    expect(refundPledge).not.toHaveBeenCalled();
  });

  it("can void instead", async () => {
    show();
    vi.mocked(demoPlay).mockResolvedValue({ pledge: row("mine-0001", "voided"), play: play("mine-0001", [], "voided") });
    fireEvent.click(await screen.findByTestId("own-void-mine-0001"));
    await waitFor(() => expect(screen.getByTestId("demo-play-note")).toHaveTextContent("hold released in the PayPal sandbox. Nothing was charged."));
    expect(demoPlay).toHaveBeenCalledWith("mine-0001", "void");
    expect(screen.queryByTestId("own-actions-mine-0001")).toBeNull();
  });

  it("shows the server's refusal and changes nothing", async () => {
    show();
    vi.mocked(demoPlay).mockRejectedValue(new Error("this pledge was not made from this browser"));
    fireEvent.click(await screen.findByTestId("own-simulate_arrival-mine-0001"));
    expect(await screen.findByText("this pledge was not made from this browser")).toBeInTheDocument();
    expect(screen.getByTestId("own-simulate_arrival-mine-0001")).toBeEnabled();
    expect(screen.queryByTestId("demo-play-note")).toBeNull();
  });

  it("runs one action at a time", async () => {
    show();
    let finish!: (value: Awaited<ReturnType<typeof demoPlay>>) => void;
    vi.mocked(demoPlay).mockReturnValue(new Promise((resolve) => { finish = resolve; }));
    fireEvent.click(await screen.findByTestId("own-simulate_arrival-mine-0001"));
    await waitFor(() => expect(screen.getByTestId("own-void-mine-0001")).toBeDisabled());
    fireEvent.click(screen.getByTestId("own-void-mine-0001"));
    expect(demoPlay).toHaveBeenCalledTimes(1);
    await act(async () => finish({ pledge: row("mine-0001"), play: play("mine-0001", ["approve", "void"]) }));
    expect(screen.getByTestId("own-void-mine-0001")).toBeEnabled();
  });

  it("shows no live button when it cannot learn which pledges are the visitor's", async () => {
    vi.mocked(fetchOwnDemoPledges).mockRejectedValue(new Error("down"));
    show();
    await waitFor(() => expect(fetchOwnDemoPledges).toHaveBeenCalled());
    await act(async () => {});
    expect(screen.queryByText("Yours")).toBeNull();
    expect(screen.queryByRole("button", { name: /Simulate arrival/ })).toBeNull();
  });

  it("offers a refund on the visitor's own captured pledge", async () => {
    vi.mocked(fetchOwnDemoPledges).mockResolvedValue([play("mine-0001", ["refund"], "captured")]);
    show({ pledges: [row("mine-0001", "captured"), row("theirs-0002", "captured")] });
    expect(await screen.findByTestId("own-refund-mine-0001")).toBeEnabled();
    expect(screen.getByTestId("own-step-mine-0001")).toHaveTextContent("Captured in the PayPal sandbox. You can refund it.");
    // The other captured pledge keeps the treasurer's refund button, disabled without the key.
    expect(screen.getByTestId("refund-theirs-0002")).toBeDisabled();
    expect(screen.queryByTestId("refund-mine-0001")).toBeNull();
  });

  it("is written in French too", async () => {
    await i18n.changeLanguage("fr");
    show();
    expect(await screen.findByTestId("own-tag-mine-0001")).toHaveTextContent("À vous");
    expect(screen.getByRole("button", { name: "Simuler l’arrivée" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Annuler" })).toBeInTheDocument();
    expect(screen.getByTestId("treasurer-demo-readonly")).toHaveTextContent("Seul le navigateur qui a fait une promesse peut agir dessus ici.");
  });
});

describe("the keyed treasurer view is unchanged", () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    await i18n.changeLanguage("en");
    vi.mocked(captainReview).mockResolvedValue({ milestone_id: "dep-la-rochelle", proposal: "capture", pledge_ids: [] });
    vi.mocked(fetchOwnDemoPledges).mockResolvedValue([play("mine-0001", ["simulate_arrival", "void"])]);
  });

  it("never asks about own pledges and shows no demo control with the treasurer key", async () => {
    show({ adminKey: "treasurer-key", demoTreasurer: false });
    await screen.findByTestId("capture-mine-0001");
    expect(fetchOwnDemoPledges).not.toHaveBeenCalled();
    expect(screen.queryByText("Yours")).toBeNull();
    expect(screen.queryByTestId("own-actions-mine-0001")).toBeNull();
    expect(screen.queryByTestId("treasurer-demo-readonly")).toBeNull();
    // The treasurer's own capture buttons are there for both pledges.
    expect(screen.getByTestId("capture-mine-0001")).toBeInTheDocument();
    expect(screen.getByTestId("capture-theirs-0002")).toBeInTheDocument();
    expect(demoPlay).not.toHaveBeenCalled();
  });
});

describe("demo treasurer page hint", () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    await i18n.changeLanguage("en");
    vi.mocked(fetchOwnDemoPledges).mockResolvedValue([]);
  });

  const panel = (demoMode: boolean) =>
    render(
      <I18nextProvider i18n={i18n}>
        <TreasurerPanel
          open onOpenChange={() => {}} demoMode={demoMode} stopNames={stopNames} adminKey="" onAdminKeyChange={() => {}}
          settleBusy={false} settleNote={null} onSettle={() => {}} clockPinned={false} settleAt="" onSettleAtChange={() => {}} onSettleAt={() => {}}
          milestoneId="" onMilestoneIdChange={() => {}} projectFund={null} boatFund={null} pledges={[]} loading={false} error={null} needsKey={false}
          onRefreshQueue={() => {}} onPledgeUpdated={() => {}} spendAmount="" onSpendAmountChange={() => {}} spendNote="" onSpendNoteChange={() => {}} onSpendSubmit={() => {}} fund={null} spendError={null}
        />
      </I18nextProvider>,
    );

  it("tells the visitor how to play, in three steps", () => {
    panel(true);
    const hint = screen.getByTestId("demo-play-hint");
    expect(within(hint).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "Pledge on a stop",
      "Come back here",
      "Approve, capture or void it",
    ]);
    expect(screen.getByTestId("demo-treasurer-banner")).toHaveTextContent("you can play the treasurer on pledges made from this browser");
  });

  it("says it in French", async () => {
    await i18n.changeLanguage("fr");
    panel(true);
    expect(within(screen.getByTestId("demo-play-hint")).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "Faites une promesse sur une escale",
      "Revenez ici",
      "Approuvez, encaissez ou annulez-la",
    ]);
  });

  it("is not shown to the keyed treasurer", () => {
    panel(false);
    expect(screen.queryByTestId("demo-play-hint")).toBeNull();
  });
});

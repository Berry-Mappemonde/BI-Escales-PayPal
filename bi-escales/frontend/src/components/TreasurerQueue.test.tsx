import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  approveCaptainReview,
  captainReview,
  capturePledge,
  refundPledge,
  voidPledge,
} from "../api/escales";
import i18n from "../i18n";
import { TreasurerQueue } from "./TreasurerQueue";

vi.mock("../api/escales", () => ({
  approveCaptainReview: vi.fn(),
  captainReview: vi.fn(),
  capturePledge: vi.fn(),
  fetchSchedule: vi.fn().mockResolvedValue({}),
  refundPledge: vi.fn(),
  voidPledge: vi.fn(),
}));

const pledge = {
  id: "p-1",
  status: "authorized" as const,
  intent: "AUTHORIZE",
  currency: "EUR",
  amount_eur: "20.00",
  description: "milles",
  milestone_id: "dep-la-rochelle",
};

describe("TreasurerQueue", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.useRealTimers());
  it("records review approval then captures on a separate button", async () => {
    await i18n.changeLanguage("fr");
    vi.mocked(captainReview).mockResolvedValue({
      milestone_id: "dep-la-rochelle",
      proposal: "capture",
      pledge_ids: ["p-1"],
    });
    vi.mocked(approveCaptainReview).mockResolvedValue({
      milestone_id: "dep-la-rochelle",
      approved: true,
    });
    vi.mocked(capturePledge).mockResolvedValue({ ...pledge, status: "captured" });
    const onUpdated = vi.fn();
    render(
      <I18nextProvider i18n={i18n}>
        <TreasurerQueue
          pledges={[pledge]}
          adminKey="test-admin-key"
          onRefresh={() => {}}
          onUpdated={onUpdated}
        />
      </I18nextProvider>,
    );
    expect(await screen.findByTestId("captain-proposal-dep-la-rochelle")).toHaveTextContent("Encaisser");
    fireEvent.click(screen.getByTestId("captain-approve-dep-la-rochelle"));
    expect(approveCaptainReview).toHaveBeenCalledWith("dep-la-rochelle", "test-admin-key", undefined);
    await waitFor(() => {
      expect(screen.getByTestId("capture-p-1")).not.toBeDisabled();
    });
    fireEvent.click(screen.getByRole("button", { name: "Capturer la promesse" }));
    expect(capturePledge).toHaveBeenCalledWith("p-1", "test-admin-key", undefined);
    await waitFor(() => {
      expect(onUpdated).toHaveBeenCalled();
    });
  });

  it("lists captured and partially refunded pledges with a refund button", async () => {
    await i18n.changeLanguage("en");
    vi.mocked(captainReview).mockResolvedValue({ milestone_id: "dep-la-rochelle", proposal: "", pledge_ids: [] });
    vi.mocked(refundPledge).mockResolvedValue({ ...pledge, id: "p-cap", status: "refunded" });
    const onUpdated = vi.fn();
    render(
      <I18nextProvider i18n={i18n}>
        <TreasurerQueue
          pledges={[
            { ...pledge, id: "p-cap", status: "captured" as const, capture_id: "CAP-1" },
            { ...pledge, id: "p-part", status: "partially_refunded" as const, refunded_amount_eur: "5.00", capture_id: "CAP-2" },
            { ...pledge, id: "p-void", status: "voided" as const },
          ]}
          adminKey="test-admin-key"
          onRefresh={() => {}}
          onUpdated={onUpdated}
        />
      </I18nextProvider>,
    );
    expect(screen.getByTestId("queue-row-p-cap")).toBeInTheDocument();
    expect(screen.getByTestId("queue-row-p-part")).toBeInTheDocument();
    expect(screen.queryByTestId("queue-row-p-void")).toBeNull();
    expect(screen.getByTestId("refund-p-part")).not.toBeDisabled();
    expect(screen.queryByTestId("void-p-cap")).toBeNull();
    fireEvent.click(screen.getByTestId("refund-p-cap"));
    expect(refundPledge).not.toHaveBeenCalled();
    expect(screen.getByRole("group", { name: "Refund €20.00 to the donor? This can't be undone." })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(refundPledge).toHaveBeenCalledTimes(1);
    expect(refundPledge).toHaveBeenCalledWith("p-cap", "test-admin-key", "20.00", undefined);
    await waitFor(() => expect(onUpdated).toHaveBeenCalled());
  });

  it("keeps money buttons disabled in keyless demo mode", async () => {
    await i18n.changeLanguage("en");
    vi.mocked(captainReview).mockResolvedValue({ milestone_id: "dep-la-rochelle", proposal: "capture", pledge_ids: [] });
    vi.mocked(voidPledge).mockClear();
    render(
      <I18nextProvider i18n={i18n}>
        <TreasurerQueue
          pledges={[pledge, { ...pledge, id: "p-cap", status: "captured" as const }]}
          adminKey=""
          demoTreasurer
          onRefresh={() => {}}
          onUpdated={() => {}}
        />
      </I18nextProvider>,
    );
    expect(screen.getByTestId("treasurer-demo-readonly")).toBeInTheDocument();
    await screen.findByTestId("captain-proposal-dep-la-rochelle");
    expect(screen.getByTestId("captain-approve-dep-la-rochelle")).toBeDisabled();
    expect(screen.getByTestId("captain-override-dep-la-rochelle")).toBeDisabled();
    expect(screen.getByTestId("refund-p-cap")).toBeDisabled();
    fireEvent.click(screen.getByTestId("captain-override-dep-la-rochelle"));
    expect(screen.queryByTestId("captain-release-dep-la-rochelle")).toBeNull();
    expect(voidPledge).not.toHaveBeenCalled();
  });

  function renderQueue(rows = [{ ...pledge, status: "captured" as const, capture_id: "CAP-1" }]) {
    return render(<I18nextProvider i18n={i18n}>
      <TreasurerQueue pledges={rows} adminKey="test-admin-key" onRefresh={() => {}} onUpdated={vi.fn()} />
    </I18nextProvider>);
  }

  it.each(["en", "fr"])("cancels refunds without a request, in %s", async (lang) => {
    await i18n.changeLanguage(lang);
    renderQueue();
    fireEvent.click(screen.getByTestId("refund-p-1"));
    const group = screen.getByRole("group");
    expect(group).toHaveTextContent(lang === "fr"
      ? "Rembourser 20,00 € au donateur ? Cette opération est irréversible."
      : "Refund €20.00 to the donor? This can't be undone.");
    const cancel = within(group).getByRole("button", { name: lang === "fr" ? "Annuler" : "Cancel" });
    expect(cancel).toHaveFocus();
    fireEvent.click(cancel);
    expect(screen.queryByRole("group")).toBeNull();
    expect(refundPledge).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.getByTestId("refund-p-1")).toHaveFocus());
  });

  it("confirms the remaining balance after a partial refund", async () => {
    await i18n.changeLanguage("en");
    render(<I18nextProvider i18n={i18n}>
      <TreasurerQueue pledges={[{ ...pledge, status: "partially_refunded", refunded_amount_eur: "7.35" }]}
        adminKey="key" onRefresh={() => {}} onUpdated={vi.fn()} />
    </I18nextProvider>);
    fireEvent.click(screen.getByTestId("refund-p-1"));
    expect(screen.getByRole("group")).toHaveTextContent("Refund €12.65 to the donor?");
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(refundPledge).toHaveBeenCalledWith("p-1", "key", "12.65", undefined);
  });

  it("confirms the amount of an interrupted keyed refund", async () => {
    await i18n.changeLanguage("en");
    render(<I18nextProvider i18n={i18n}>
      <TreasurerQueue pledges={[{ ...pledge, status: "captured", pending_refund: { key: "refund-p-1-1", amount: "5.00" } }]}
        adminKey="key" onRefresh={() => {}} onUpdated={vi.fn()} />
    </I18nextProvider>);
    fireEvent.click(screen.getByTestId("refund-p-1"));
    expect(screen.getByRole("group")).toHaveTextContent("Refund €5.00 to the donor?");
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(refundPledge).toHaveBeenCalledWith("p-1", "key", "5.00", undefined);
  });

  it("sends one refund while busy and requires confirmation again after an error", async () => {
    await i18n.changeLanguage("en");
    let reject!: (error: Error) => void;
    vi.mocked(refundPledge).mockImplementationOnce(() => new Promise((_, fail) => { reject = fail; }));
    renderQueue();
    fireEvent.click(screen.getByTestId("refund-p-1"));
    const confirm = screen.getByRole("button", { name: "Confirm" });
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    expect(refundPledge).toHaveBeenCalledTimes(1);
    expect(confirm).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    await act(async () => reject(new Error("PayPal unavailable")));
    expect(screen.getByText("PayPal unavailable")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm" })).not.toBeDisabled();
    expect(refundPledge).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("group")).toBeNull();
  });

  it("drops the confirmation when the refundable balance changes", async () => {
    await i18n.changeLanguage("en");
    const view = renderQueue();
    fireEvent.click(screen.getByTestId("refund-p-1"));
    view.rerender(<I18nextProvider i18n={i18n}>
      <TreasurerQueue pledges={[{ ...pledge, status: "partially_refunded", refunded_amount_eur: "5.00" }]}
        adminKey="test-admin-key" onRefresh={() => {}} onUpdated={vi.fn()} />
    </I18nextProvider>);
    expect(screen.queryByRole("group")).toBeNull();
    expect(refundPledge).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("refund-p-1"));
    expect(screen.getByRole("group")).toHaveTextContent("Refund €15.00 to the donor?");
  });

  it.each(["en", "fr"])("confirms or cancels voids inline, keeping Undo, in %s", async (lang) => {
    await i18n.changeLanguage(lang);
    vi.mocked(captainReview).mockResolvedValue({ milestone_id: pledge.milestone_id, proposal: "wait", pledge_ids: [pledge.id] });
    vi.mocked(voidPledge).mockResolvedValue({ ...pledge, status: "voided" });
    render(<I18nextProvider i18n={i18n}>
      <TreasurerQueue pledges={[pledge]} adminKey="key" onRefresh={() => {}} onUpdated={vi.fn()} />
    </I18nextProvider>);
    await screen.findByTestId(`captain-proposal-${pledge.milestone_id}`);
    const open = () => fireEvent.click(screen.getByTestId(`captain-override-${pledge.milestone_id}`));
    open();
    expect(screen.getByRole("group")).toHaveTextContent(lang === "fr"
      ? "Annuler 1 retenue de 20 € ? Une fois envoyée, cette opération est irréversible."
      : "Void 1 hold of €20? Once sent, this can't be undone.");
    fireEvent.click(screen.getByRole("button", { name: lang === "fr" ? "Annuler" : "Cancel" }));
    expect(voidPledge).not.toHaveBeenCalled();
    expect(screen.queryByRole("group")).toBeNull();
    open();
    vi.useFakeTimers();
    fireEvent.click(screen.getByRole("button", { name: lang === "fr" ? "Confirmer" : "Confirm" }));
    expect(voidPledge).not.toHaveBeenCalled();
    await act(() => vi.advanceTimersByTimeAsync(5000));
    expect(voidPledge).toHaveBeenCalledTimes(1);
    expect(voidPledge).toHaveBeenCalledWith(pledge.id, "key", undefined);
  });


  it("requires refreshed data if the partial refund balance is unknown", async () => {
    await i18n.changeLanguage("en");
    render(<I18nextProvider i18n={i18n}>
      <TreasurerQueue pledges={[{ ...pledge, status: "partially_refunded" }]}
        adminKey="key" onRefresh={() => {}} onUpdated={vi.fn()} />
    </I18nextProvider>);
    expect(screen.getByTestId("refund-p-1")).toBeDisabled();
    expect(screen.getByTestId("refund-p-1")).toHaveAttribute("title", "Refresh the queue to load the refundable amount.");
    fireEvent.click(screen.getByTestId("refund-p-1"));
    expect(refundPledge).not.toHaveBeenCalled();
  });

});

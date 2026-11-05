import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { describe, expect, it, vi } from "vitest";
import { approveCaptainReview, captainReview, capturePledge, refundPledge, voidPledge } from "../api/escales";
import i18n from "../i18n";
import { TreasurerQueue } from "./TreasurerQueue";

vi.mock("../api/escales", () => ({
  approveCaptainReview: vi.fn(),
  captainReview: vi.fn(),
  capturePledge: vi.fn(),
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
    expect(await screen.findByTestId("verdict-p-1")).toHaveTextContent("capture");
    fireEvent.click(screen.getByRole("button", { name: "Approuver la revue" }));
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
            { ...pledge, id: "p-part", status: "partially_refunded" as const, capture_id: "CAP-2" },
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
    expect(refundPledge).toHaveBeenCalledWith("p-cap", "test-admin-key", undefined, undefined);
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
    expect(screen.getByTestId("approve-p-1")).toBeDisabled();
    expect(screen.getByTestId("void-p-1")).toBeDisabled();
    expect(screen.getByTestId("refund-p-cap")).toBeDisabled();
    fireEvent.click(screen.getByTestId("void-p-1"));
    expect(voidPledge).not.toHaveBeenCalled();
  });
});

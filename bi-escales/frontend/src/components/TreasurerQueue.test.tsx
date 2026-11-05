import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { describe, expect, it, vi } from "vitest";
import { approveCaptainReview, captainReview, capturePledge, voidPledge } from "../api/escales";
import i18n from "../i18n";
import { TreasurerQueue } from "./TreasurerQueue";

vi.mock("../api/escales", () => ({
  approveCaptainReview: vi.fn(),
  captainReview: vi.fn(),
  capturePledge: vi.fn(),
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
    expect(approveCaptainReview).toHaveBeenCalledWith("dep-la-rochelle", "test-admin-key");
    await waitFor(() => {
      expect(screen.getByTestId("capture-p-1")).not.toBeDisabled();
    });
    fireEvent.click(screen.getByRole("button", { name: "Capturer la promesse" }));
    expect(capturePledge).toHaveBeenCalledWith("p-1", "test-admin-key");
    await waitFor(() => {
      expect(onUpdated).toHaveBeenCalled();
    });
  });
});

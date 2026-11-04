import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { describe, expect, it, vi } from "vitest";
import { captainReview, capturePledge, voidPledge } from "../api/escales";
import i18n from "../i18n";
import { TreasurerQueue } from "./TreasurerQueue";

vi.mock("../api/escales", () => ({
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
  it("approuve le verdict du capitaine avec le tableau HTML par défaut", async () => {
    vi.stubEnv("VITE_ENABLE_AG_GRID", "0");
    await i18n.changeLanguage("fr");
    vi.mocked(captainReview).mockResolvedValue({
      milestone_id: "dep-la-rochelle",
      proposal: "capture",
      pledge_ids: ["p-1"],
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
    expect(screen.getByTestId("treasurer-queue-fallback-table")).toBeInTheDocument();
    expect(screen.queryByTestId("treasurer-queue-ag-grid")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Approuver la revue" }));
    await waitFor(() => expect(capturePledge).toHaveBeenCalledWith("p-1", "test-admin-key"));
    await waitFor(() => expect(onUpdated).toHaveBeenCalled());
  });

  it("affiche la grille AG Grid quand le drapeau est activé", async () => {
    vi.stubEnv("VITE_ENABLE_AG_GRID", "1");
    await i18n.changeLanguage("fr");
    vi.mocked(captainReview).mockResolvedValue({
      milestone_id: "dep-la-rochelle",
      proposal: "capture",
      pledge_ids: ["p-1"],
    });
    render(
      <I18nextProvider i18n={i18n}>
        <TreasurerQueue
          pledges={[pledge]}
          adminKey="test-admin-key"
          onRefresh={() => {}}
          onUpdated={() => {}}
        />
      </I18nextProvider>,
    );
    expect(await screen.findByTestId("treasurer-queue-ag-grid")).toBeInTheDocument();
    expect(document.querySelector(".ag-header")).toBeTruthy();
    expect(screen.queryByTestId("treasurer-queue-fallback-table")).toBeNull();
  });
});

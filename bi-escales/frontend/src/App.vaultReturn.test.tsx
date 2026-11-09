import { render, screen, waitFor } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "./i18n";
import App from "./App";
import { registerVault } from "./api/escales";

vi.mock("./hooks/usePledgeQueue", () => ({
  usePledgeQueue: () => ({
    pledges: [],
    loading: false,
    error: null,
    needsKey: true,
    refresh: vi.fn(),
    updatePledge: vi.fn(),
  }),
}));

vi.mock("./api/escales", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./api/escales")>();
  return {
    ...actual,
    registerVault: vi.fn(),
    authorizePledge: vi.fn(),
    fetchHealthRetrying: vi.fn().mockResolvedValue({ status: "ok" }),
    fetchSchedule: vi.fn().mockResolvedValue({ milestones: [], legs: [], export: {}, prices: { prices: [] } }),
    fetchFund: vi.fn(),
    recordSpending: vi.fn(),
  };
});

vi.mock("./voyage/loadVoyage.js", () => ({
  fetchJson: vi.fn().mockResolvedValue(null),
  sampleAt: vi.fn(),
  voyageFromRoute: vi.fn(),
}));

vi.mock("./map/MapScene.jsx", () => ({ MapScene: () => null }));
vi.mock("./components/EscalePopup.jsx", () => ({ EscalePopup: () => null }));
vi.mock("./components/EscalesPanel", () => ({ EscalesPanel: () => null }));
vi.mock("./components/escales/EscalesScheduler.jsx", () => ({ default: () => null }));
vi.mock("./components/MarinasPanel.jsx", () => ({ default: () => null }));
vi.mock("./components/ProjectList.jsx", () => ({ default: () => null }));
vi.mock("./components/TreasurerQueue", () => ({ TreasurerQueue: () => null }));
vi.mock("./marinas/escaleFiche.js", () => ({
  loadEscaleFiche: vi.fn(),
  loadEscaleMarinasGeojson: vi.fn().mockResolvedValue({ type: "FeatureCollection", features: [] }),
  loadAllEscalesMarinasGeojson: vi.fn().mockResolvedValue({ type: "FeatureCollection", features: [] }),
  ficheMarinas: vi.fn(() => ({ type: "FeatureCollection", features: [] })),
}));

describe("App vault return", () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    await i18n.changeLanguage("en");
  });

  it("shows success after registerVault resolves", async () => {
    vi.mocked(registerVault).mockResolvedValue({
      id: "p-vault",
      status: "vaulted",
      intent: "VAULT",
      payment_mode: "VAULT",
      currency: "EUR",
      amount_eur: "20.00",
      description: "miles",
      milestone_id: "dep-mayotte",
    });

    const replaceState = vi.spyOn(window.history, "replaceState").mockImplementation(() => {});
    vi.stubGlobal("location", {
      ...window.location,
      search: "?vault=return&pledge_id=p-vault&approval_token_id=tok1",
      pathname: "/",
      href: "http://localhost/?vault=return&pledge_id=p-vault&approval_token_id=tok1",
      hash: "",
    });

    render(
      <I18nextProvider i18n={i18n}>
        <App />
      </I18nextProvider>,
    );

    expect(screen.getByText("Saving the payment method…")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText("Saved — captured on arrival (voided if the stop is cancelled)")).toBeInTheDocument();
    });
    expect(registerVault).toHaveBeenCalledWith("p-vault", "tok1");
    replaceState.mockRestore();
  });

  it("shows an error state when registerVault fails", async () => {
    vi.mocked(registerVault).mockRejectedValue(new Error("order not approved"));
    vi.spyOn(window.history, "replaceState").mockImplementation(() => {});
    vi.stubGlobal("location", {
      ...window.location,
      search: "?vault=return&pledge_id=p-vault&approval_token_id=tok1",
      pathname: "/",
      href: "http://localhost/?vault=return&pledge_id=p-vault",
      hash: "",
    });

    render(
      <I18nextProvider i18n={i18n}>
        <App />
      </I18nextProvider>,
    );

    await waitFor(() => {
      expect(screen.getByText(/Could not save the payment method/)).toBeInTheDocument();
    });
    expect(screen.queryByText("Saving the payment method…")).toBeNull();
  });
});

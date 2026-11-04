import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { I18nextProvider } from "react-i18next";
import { beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "./i18n";
import App from "./App";
import * as escalesApi from "./api/escales";
import { settleClock } from "./api/escales";

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
    settleClock: vi.fn(),
    fetchFeatures: vi.fn().mockResolvedValue({ clock_pinned: false }),
    authorizePledge: vi.fn(),
    registerVault: vi.fn(),
    fetchHealthRetrying: vi.fn().mockResolvedValue({ status: "ok" }),
    fetchSchedule: vi.fn().mockResolvedValue({ milestones: [], legs: [], export: {}, prices: { prices: [] } }),
    fetchFund: vi.fn().mockResolvedValue({
      balance_eur: "0.00",
      currency: "EUR",
      income_eur: "0.00",
      spending_eur: "0.00",
    }),
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
vi.mock("./marinas/escaleFiche.js", () => ({ loadEscaleFiche: vi.fn(), ficheMarinas: vi.fn(() => []) }));

describe("departure-day settle", () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    await i18n.changeLanguage("en");
    vi.mocked(escalesApi.fetchFeatures).mockResolvedValue({ clock_pinned: false });
    vi.stubGlobal("location", {
      ...window.location,
      hash: "#tresorier",
      search: "",
      pathname: "/",
      href: "http://localhost/#tresorier",
    });
  });

  it("stays disabled until the masked treasurer key is set, then posts that key", async () => {
    vi.mocked(settleClock).mockResolvedValue({ settled: [] });
    const user = userEvent.setup();
    render(
      <I18nextProvider i18n={i18n}>
        <App />
      </I18nextProvider>,
    );

    const button = await waitFor(() => screen.getByTestId("departure-settle"));
    expect(button).toHaveTextContent("Run departure-day settle");
    expect(button).toBeDisabled();
    await user.click(button);
    expect(settleClock).not.toHaveBeenCalled();

    const key = screen.getByTestId("admin-key-input");
    expect(key).toHaveAttribute("type", "password");
    await user.type(key, "secret-admin");
    expect(button).toBeEnabled();
    await user.click(button);
    expect(settleClock).toHaveBeenCalledTimes(1);
    expect(settleClock).toHaveBeenCalledWith("secret-admin");
  });

  it("shows settle-at controls only when the clock is pinned", async () => {
    vi.mocked(escalesApi.fetchFeatures).mockResolvedValue({ clock_pinned: true });
    vi.mocked(settleClock).mockResolvedValue({ settled: [] });
    const user = userEvent.setup();
    render(
      <I18nextProvider i18n={i18n}>
        <App />
      </I18nextProvider>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("settle-at-input")).toBeInTheDocument();
    });
    const atButton = screen.getByTestId("settle-at-chosen-button");
    expect(atButton).toBeDisabled();
    await user.type(screen.getByTestId("admin-key-input"), "secret-admin");
    await user.type(screen.getByTestId("settle-at-input"), "2026-11-20T08:00");
    expect(atButton).toBeEnabled();
    await user.click(atButton);
    expect(settleClock).toHaveBeenCalledWith("secret-admin", expect.stringMatching(/2026-11-20/));
  });
});

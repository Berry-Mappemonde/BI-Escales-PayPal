import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { I18nextProvider } from "react-i18next";
import { beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "./i18n";
import App from "./App";
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

    const button = screen.getByTestId("departure-settle");
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
});

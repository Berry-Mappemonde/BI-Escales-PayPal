import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { I18nextProvider } from "react-i18next";
import { beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "./i18n";
import App from "./App";
import * as escalesApi from "./api/escales";

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
    fetchHealthRetrying: vi.fn().mockResolvedValue({ status: "ok" }),
    fetchFeatures: vi.fn().mockResolvedValue({ clock_pinned: false }),
    authorizePledge: vi.fn(),
    registerVault: vi.fn(),
    fetchFund: vi.fn().mockResolvedValue({
      balance_eur: "0.00",
      currency: "EUR",
      income_eur: "0.00",
      spending_eur: "0.00",
    }),
    settleClock: vi.fn(),
  };
});

vi.mock("./voyage/loadVoyage.js", () => ({
  fetchJson: vi.fn().mockResolvedValue(null),
  sampleAt: vi.fn(),
  voyageFromRoute: vi.fn(),
}));

vi.mock("./map/MapScene.jsx", () => ({ MapScene: () => <div data-testid="voyage-map" /> }));
vi.mock("./components/EscalePopup.jsx", () => ({ EscalePopup: () => null }));
vi.mock("./components/EscalesPanel", () => ({ EscalesPanel: () => <div data-testid="captain-panel" /> }));
vi.mock("./components/MarinasPanel.jsx", () => ({ default: () => <div data-testid="marinas-panel" /> }));
vi.mock("./components/ProjectList.jsx", () => ({ default: () => null }));
vi.mock("./components/CrewSubscribeButton", () => ({ CrewSubscribeButton: () => <span>Crew</span> }));
vi.mock("./marinas/escaleFiche.js", () => ({
  loadEscaleFiche: vi.fn(),
  loadEscaleMarinasGeojson: vi.fn().mockResolvedValue({ type: "FeatureCollection", features: [] }),
  loadAllEscalesMarinasGeojson: vi.fn().mockResolvedValue({ type: "FeatureCollection", features: [] }),
  ficheMarinas: vi.fn(() => ({ type: "FeatureCollection", features: [] })),
}));

describe("NAVIGUIDE shell wiring", () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    await i18n.changeLanguage("en");
    vi.stubGlobal("location", {
      ...window.location,
      hash: "",
      search: "",
      pathname: "/",
      href: "http://localhost/",
    });
    document.body.className = "";
  });

  it("renders full-screen shell with map, sidebar and tools panel", () => {
    render(
      <I18nextProvider i18n={i18n}>
        <App />
      </I18nextProvider>,
    );
    expect(screen.getByTestId("ng-shell")).toBeInTheDocument();
    expect(screen.getByTestId("ng-sidebar")).toBeInTheDocument();
    expect(screen.getByTestId("ng-tools-panel")).toBeInTheDocument();
    expect(screen.getByTestId("voyage-map")).toBeInTheDocument();
    expect(screen.getByTestId("captain-panel")).toBeInTheDocument();
    expect(screen.getByTestId("crew-supporter-public")).toBeInTheDocument();
  });

  it("switches marinas tab to the marinas tools panel", async () => {
    const user = userEvent.setup();
    render(
      <I18nextProvider i18n={i18n}>
        <App />
      </I18nextProvider>,
    );
    await user.click(screen.getByRole("tab", { name: /marinas/i }));
    expect(screen.getByTestId("marinas-panel")).toBeInTheDocument();
  });

  it("treasurer hash keeps settle control wired", async () => {
    vi.mocked(escalesApi.settleClock).mockResolvedValue({ settled: { actions: [] } });
    vi.stubGlobal("location", {
      ...window.location,
      hash: "#tresorier",
      href: "http://localhost/#tresorier",
    });
    render(
      <I18nextProvider i18n={i18n}>
        <App />
      </I18nextProvider>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("departure-settle")).toBeDisabled();
    });
    expect(screen.getByTestId("ng-shell")).toBeInTheDocument();
  });

  it("reopens the left sidebar after collapse and closes the right tools panel", async () => {
    const user = userEvent.setup();
    render(
      <I18nextProvider i18n={i18n}>
        <App />
      </I18nextProvider>,
    );
    const leftToggle = screen.getByTestId("ng-sidebar-toggle");
    const toolsToggle = screen.getByTestId("ng-tools-toggle");
    const sidebar = screen.getByTestId("ng-sidebar");
    const tools = screen.getByTestId("ng-tools-panel");

    expect(sidebar.className).not.toMatch(/ng-collapsed/);
    await user.click(leftToggle);
    expect(sidebar.className).toMatch(/ng-collapsed/);
    await user.click(leftToggle);
    expect(sidebar.className).not.toMatch(/ng-collapsed/);

    expect(tools.className).not.toMatch(/ng-collapsed/);
    await user.click(toolsToggle);
    expect(tools.className).toMatch(/ng-collapsed/);
    await user.click(toolsToggle);
    expect(tools.className).not.toMatch(/ng-collapsed/);
  });

});

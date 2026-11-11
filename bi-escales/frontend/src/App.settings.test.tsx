import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { I18nextProvider } from "react-i18next";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "./i18n";
import App from "./App";

const queued = vi.hoisted(() => ({ pledges: [] as unknown[] }));

vi.mock("./hooks/usePledgeQueue", () => ({
  usePledgeQueue: (_adminKey: string, demoTreasurer?: boolean) => ({
    pledges: demoTreasurer ? queued.pledges : [],
    loading: false,
    error: null,
    needsKey: !demoTreasurer,
    refresh: vi.fn(),
    updatePledge: vi.fn(),
  }),
}));

vi.mock("./api/escales", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./api/escales")>();
  return {
    ...actual,
    fetchHealthRetrying: vi.fn().mockResolvedValue({ status: "ok" }),
    fetchFeatures: vi.fn().mockResolvedValue({ clock_pinned: false, demo_treasurer: true }),
    fetchFund: vi.fn().mockResolvedValue({
      balance_eur: "0.00",
      currency: "EUR",
      income_eur: "0.00",
      spending_eur: "0.00",
    }),
    listPledges: vi.fn().mockResolvedValue([]),
  };
});

vi.mock("./voyage/loadVoyage.js", () => ({
  fetchJson: vi.fn().mockResolvedValue({ type: "FeatureCollection", features: [] }),
  sampleAt: vi.fn(() => null),
  voyageFromRoute: vi.fn(() => ({
    stops: [
      { name: "La Rochelle", lat: 46.16, lon: -1.15, milestoneId: "dep-la-rochelle" },
      { name: "Ajaccio (Corse)", lat: 41.92, lon: 8.73, milestoneId: "dep-ajaccio-corse" },
    ],
    segments: [],
    clock: {},
  })),
}));

vi.mock("./map/MapScene.jsx", () => ({ MapScene: () => <div data-testid="voyage-map" /> }));
vi.mock("./components/EscalePopup.jsx", () => ({ EscalePopup: () => null }));
vi.mock("./components/EscalesPanel", () => ({ EscalesPanel: () => null }));
vi.mock("./components/MarinasPanel.jsx", () => ({ default: () => null }));
vi.mock("./components/ProjectList.jsx", () => ({ default: () => null }));
vi.mock("./components/CrewSubscribeButton", () => ({
  CrewSubscribeButton: () => null,
  CrewSupporterPublicSection: () => null,
}));
vi.mock("./marinas/escaleFiche.js", () => ({
  loadEscaleFiche: vi.fn(),
  loadEscaleMarinasGeojson: vi.fn().mockResolvedValue({ type: "FeatureCollection", features: [] }),
  loadAllEscalesMarinasGeojson: vi.fn().mockResolvedValue({ type: "FeatureCollection", features: [] }),
  ficheMarinas: vi.fn(() => ({ type: "FeatureCollection", features: [] })),
}));

/** B13: app settings stay separate from the visitor tools and from the treasurer tools. */
describe("App settings", () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    queued.pledges = [];
    localStorage.clear();
    await i18n.changeLanguage("en");
    vi.stubGlobal("location", { ...window.location, hash: "", search: "", pathname: "/", href: "http://localhost/" });
    vi.stubGlobal("history", { ...window.history, replaceState: vi.fn() });
  });
  afterEach(async () => {
    localStorage.clear();
    await i18n.changeLanguage("en");
  });

  function renderApp() {
    render(
      <I18nextProvider i18n={i18n}>
        <App />
      </I18nextProvider>,
    );
  }

  it("shows one Settings group in the rail's masthead, outside the visitor tools", async () => {
    renderApp();
    const settings = await screen.findByTestId("shell-settings");
    expect(settings).toHaveAccessibleName("Settings");
    expect(settings.closest(".rail-masthead")).not.toBeNull();
    // Not inside the tab bar, the Captain, the project list or the footer with the treasurer entry.
    expect(settings.closest('.ng-tab-bar, .captain-chat, [data-testid="project-list"], [data-testid="rail-footer"]')).toBeNull();
    expect(screen.getAllByRole("group", { name: "Settings" })).toHaveLength(1);
  });

  it("shows the same settings on the treasurer page, in its top bar and not inside the treasurer tools", async () => {
    const user = userEvent.setup();
    renderApp();
    await user.click(await screen.findByTestId("demo-treasurer-button"));
    const page = screen.getByTestId("treasurer-page");
    const settings = within(page).getByTestId("treasurer-page-shell-settings");
    expect(settings).toHaveAccessibleName("Settings");
    expect(settings.parentElement).toBe(screen.getByTestId("treasurer-page-back").parentElement);
    expect(settings.closest(".treasurer-panel")).toBeNull();
    expect(within(page).getAllByRole("group", { name: "Settings" })).toHaveLength(1);
  });

  it("switches the language from the treasurer page, for the page and the rest of the app", async () => {
    const user = userEvent.setup();
    renderApp();
    await user.click(await screen.findByTestId("demo-treasurer-button"));
    const page = screen.getByTestId("treasurer-page");
    expect(screen.getByTestId("demo-treasurer-banner")).toHaveTextContent(/Sandbox demo: you can play the treasurer/);

    await user.click(within(page).getByRole("button", { name: i18n.t("app.langFrSwitch") }));
    await waitFor(() => expect(screen.getByTestId("demo-treasurer-banner")).toHaveTextContent(/lecture seule/i));
    expect(document.documentElement.lang).toBe("fr");
    expect(localStorage.getItem("bi-escales-lang")).toBe("fr");
    // Both copies show the same state.
    for (const group of screen.getAllByRole("group", { name: "Réglages" })) {
      expect(within(group).getByRole("button", { name: i18n.t("app.langFrSwitch") })).toHaveAttribute("aria-pressed", "true");
    }
  });

  it("switches the theme from the treasurer page", async () => {
    const user = userEvent.setup();
    renderApp();
    await user.click(await screen.findByTestId("demo-treasurer-button"));
    await waitFor(() => expect(document.documentElement.dataset.theme).toBe("dark"));
    await user.click(screen.getByTestId("treasurer-page-theme-toggle"));
    await waitFor(() => expect(document.documentElement.dataset.theme).toBe("light"));
    expect(screen.getByTestId("theme-toggle")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("treasurer-page-theme-toggle")).toHaveAttribute("aria-pressed", "true");
  });

  it("leaves the way back first in the treasurer page, and Escape still closes it", async () => {
    const user = userEvent.setup();
    renderApp();
    await user.click(await screen.findByTestId("demo-treasurer-button"));
    const back = screen.getByTestId("treasurer-page-back");
    await waitFor(() => expect(back).toHaveFocus());
    const bar = back.parentElement as HTMLElement;
    expect(bar.firstElementChild).toBe(back);
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByTestId("treasurer-page")).toBeNull());
  });
});

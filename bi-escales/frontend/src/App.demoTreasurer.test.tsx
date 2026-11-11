import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { I18nextProvider } from "react-i18next";
import { beforeEach, describe, expect, it, vi } from "vitest";
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

describe("Demo treasurer entry", () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    queued.pledges = [];
    await i18n.changeLanguage("en");
    vi.stubGlobal("location", {
      ...window.location,
      hash: "",
      search: "",
      pathname: "/",
      href: "http://localhost/",
    });
    vi.stubGlobal("history", {
      ...window.history,
      replaceState: vi.fn(),
    });
  });

  it("opens the panel with sandbox banner and no admin key field", async () => {
    const user = userEvent.setup();
    render(
      <I18nextProvider i18n={i18n}>
        <App />
      </I18nextProvider>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("demo-treasurer-button")).toBeInTheDocument();
    });
    await user.click(screen.getByTestId("demo-treasurer-button"));
    expect(screen.getByTestId("demo-treasurer-banner")).toHaveTextContent(/Sandbox demo/i);
    expect(screen.queryByTestId("admin-key-input")).toBeNull();
    expect(screen.queryByTestId("departure-settle")).toBeNull();
  });

  it("names each queued pledge's stop from the voyage the app loaded, and keeps an unknown id", async () => {
    const hold = (id: string, milestone_id: string) => ({
      id,
      status: "authorized",
      intent: "AUTHORIZE",
      currency: "EUR",
      amount_eur: "20.00",
      description: "Sponsored miles",
      milestone_id,
      created_at: "2026-11-11T09:12:00Z",
    });
    queued.pledges = [hold("p-1", "dep-la-rochelle"), hold("p-2", "dep-ajaccio-corse"), hold("p-3", "leg-not-a-stop")];
    const user = userEvent.setup();
    render(
      <I18nextProvider i18n={i18n}>
        <App />
      </I18nextProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("demo-treasurer-button")).toBeInTheDocument());
    await user.click(screen.getByTestId("demo-treasurer-button"));

    await waitFor(() => expect(screen.getByTestId("pledge-milestone-p-1")).toHaveTextContent(/^La Rochelle$/));
    expect(screen.getByTestId("pledge-milestone-p-1")).toHaveAttribute("title", "dep-la-rochelle");
    expect(screen.getByTestId("pledge-milestone-p-2")).toHaveTextContent(/^Ajaccio \(Corse\)$/);
    expect(screen.getByTestId("pledge-milestone-p-3")).toHaveTextContent(/^leg-not-a-stop$/);
  });
});

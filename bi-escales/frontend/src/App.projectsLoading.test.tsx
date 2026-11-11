import { render, screen, waitFor } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "./i18n";
import App from "./App";

const queued = vi.hoisted(() => ({ pledges: [] as unknown[] }));
const files = vi.hoisted(() => ({ projects: (): Promise<unknown> => Promise.resolve({ type: "FeatureCollection", features: [] }) }));

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
  fetchJson: vi.fn((path: string) => (path === "/bi-projects.geojson" ? files.projects() : Promise.resolve({ type: "FeatureCollection", features: [] }))),
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
vi.mock("./components/ProjectList.jsx", () => ({
  default: ({ loading, projects }: { loading?: boolean; projects?: { features?: unknown[] } }) => (
    <div data-testid="project-list-stub" data-loading={String(Boolean(loading))} data-count={String(projects?.features?.length ?? 0)} />
  ),
}));
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

/** The project list is told it is loading until the projects file has answered or failed. */
describe("Projects file loading state", () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    queued.pledges = [];
    await i18n.changeLanguage("en");
    vi.stubGlobal("location", { ...window.location, hash: "", search: "", pathname: "/", href: "http://localhost/" });
    vi.stubGlobal("history", { ...window.history, replaceState: vi.fn() });
  });

  const stub = () => screen.getByTestId("project-list-stub");
  const renderApp = () =>
    render(
      <I18nextProvider i18n={i18n}>
        <App />
      </I18nextProvider>,
    );

  it("is loading until the file arrives, then shows what it holds", async () => {
    let deliver!: (value: unknown) => void;
    files.projects = () => new Promise((resolve) => { deliver = resolve; });
    renderApp();
    expect(stub()).toHaveAttribute("data-loading", "true");
    expect(stub()).toHaveAttribute("data-count", "0");
    deliver({ type: "FeatureCollection", features: [{ type: "Feature", properties: { id: "p-1" } }, { type: "Feature", properties: { id: "p-2" } }] });
    await waitFor(() => expect(stub()).toHaveAttribute("data-loading", "false"));
    expect(stub()).toHaveAttribute("data-count", "2");
  });

  it("stops loading when the file cannot be read", async () => {
    files.projects = () => Promise.reject(new Error("down"));
    renderApp();
    await waitFor(() => expect(stub()).toHaveAttribute("data-loading", "false"));
    expect(stub()).toHaveAttribute("data-count", "0");
  });
});

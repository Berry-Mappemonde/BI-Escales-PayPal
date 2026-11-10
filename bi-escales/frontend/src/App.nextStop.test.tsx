import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { I18nextProvider } from "react-i18next";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as escalesApi from "./api/escales";
import i18n from "./i18n";
import App from "./App";

vi.mock("./hooks/usePledgeQueue", () => ({
  usePledgeQueue: () => ({ pledges: [], loading: false, error: null, needsKey: true, refresh: vi.fn(), updatePledge: vi.fn() }),
}));

const schedule = {
  export: {
    escales: [
      { milestone_id: "dep-saint-maur-berry-indre", name: "Saint-Maur (Berry, Indre)", arrival_iso: "2026-11-12T08:00:00+00:00" },
      { milestone_id: "dep-la-rochelle", name: "La Rochelle", arrival_iso: "2026-11-12T12:00:00+00:00" },
      { milestone_id: "dep-ajaccio-corse", name: "Ajaccio (Corse)", arrival_iso: "2026-11-29T02:02:52+00:00" },
    ],
  },
  legs: [],
};

vi.mock("./api/escales", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./api/escales")>();
  return {
    ...actual,
    fetchHealthRetrying: vi.fn().mockResolvedValue({ status: "ok" }),
    fetchFeatures: vi.fn().mockResolvedValue({ clock_pinned: true }),
    fetchFund: vi.fn().mockResolvedValue({}),
    fetchPublicCommonFund: vi.fn().mockResolvedValue(null),
    fetchGearProjects: vi.fn().mockResolvedValue({ features: [] }),
    fetchPrices: vi.fn().mockRejectedValue(new Error("no prices")),
    fetchSchedule: vi.fn(),
    fetchClock: vi.fn(),
    listMilestones: vi.fn(),
  };
});

const stops = [
  { name: "Saint-Maur (Berry, Indre)", lat: 46.8, lon: 1.6, milestoneId: "dep-saint-maur-berry-indre" },
  { name: "La Rochelle", lat: 46.2, lon: -1.2, milestoneId: "dep-la-rochelle" },
  { name: "Ajaccio (Corse)", lat: 41.9, lon: 8.7, milestoneId: "dep-ajaccio-corse" },
];

vi.mock("./voyage/loadVoyage.js", () => ({
  fetchJson: vi.fn().mockResolvedValue({ type: "FeatureCollection", features: [] }),
  // Before departure: the boat waits at Saint-Maur, which is what the button used to follow.
  sampleAt: vi.fn(() => ({ status: "waiting", countdownHours: 12 })),
  voyageFromRoute: vi.fn(() => ({ stops, segments: [], clock: {} })),
}));

vi.mock("./map/MapScene.jsx", () => ({ MapScene: () => <div data-testid="voyage-map" /> }));
vi.mock("./components/EscalePopup.jsx", () => ({
  EscalePopup: ({ stop }: { stop: { name: string } }) => <div data-testid="stop-sheet">{stop.name}</div>,
}));
vi.mock("./components/EscalesPanel", () => ({ EscalesPanel: () => null }));
vi.mock("./components/MarinasPanel.jsx", () => ({ default: () => null }));
vi.mock("./components/ProjectList.jsx", () => ({ default: () => null }));
vi.mock("./components/CrewSubscribeButton", () => ({
  CrewSubscribeButton: () => null,
  CrewSupporterPublicSection: () => null,
}));
vi.mock("./marinas/escaleFiche.js", () => ({
  loadEscaleFiche: vi.fn().mockResolvedValue(null),
  loadEscaleMarinasGeojson: vi.fn().mockResolvedValue({ type: "FeatureCollection", features: [] }),
  loadAllEscalesMarinasGeojson: vi.fn().mockResolvedValue({ type: "FeatureCollection", features: [] }),
  ficheMarinas: vi.fn(() => ({ type: "FeatureCollection", features: [] })),
}));

function renderApp() {
  render(
    <I18nextProvider i18n={i18n}>
      <App />
    </I18nextProvider>,
  );
}

describe("Back the next stop", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
    vi.mocked(escalesApi.fetchSchedule).mockResolvedValue(schedule as never);
    vi.mocked(escalesApi.listMilestones).mockResolvedValue([]);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("points to La Rochelle once Saint-Maur's arrival has passed on the API clock, and opens it", async () => {
    vi.mocked(escalesApi.fetchClock).mockResolvedValue({ start: "2026-11-12", now: "2026-11-12T10:00:00+00:00" });
    const user = userEvent.setup();
    renderApp();

    const button = await screen.findByTestId("back-next-stop");
    await waitFor(() => expect(button).toHaveAccessibleName("Back the next stop: La Rochelle"));
    await user.click(button);
    expect(await screen.findByTestId("stop-sheet")).toHaveTextContent("La Rochelle");
  });

  it("stays on the first stop before departure day", async () => {
    vi.mocked(escalesApi.fetchClock).mockResolvedValue({ start: "2026-11-12", now: "2026-11-10T19:00:00+00:00" });
    renderApp();
    const button = await screen.findByTestId("back-next-stop");
    await waitFor(() => expect(button).toHaveAccessibleName("Back the next stop: Saint-Maur (Berry, Indre)"));
  });

  it("skips a cancelled stop", async () => {
    vi.mocked(escalesApi.fetchClock).mockResolvedValue({ start: "2026-11-12", now: "2026-11-12T10:00:00+00:00" });
    vi.mocked(escalesApi.listMilestones).mockResolvedValue([
      { id: "dep-la-rochelle", evidence: [], meta: { cancelled: true } },
    ]);
    renderApp();
    const button = await screen.findByTestId("back-next-stop");
    await waitFor(() => expect(button).toHaveAccessibleName("Back the next stop: Ajaccio (Corse)"));
  });

  it("offers no shortcut when every stop is behind the boat", async () => {
    vi.mocked(escalesApi.fetchClock).mockResolvedValue({ start: "2026-11-12", now: "2028-01-01T00:00:00+00:00" });
    renderApp();
    await waitFor(() => expect(escalesApi.fetchClock).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByTestId("back-next-stop")).toBeNull());
    expect(screen.getByTestId("how-it-works")).toBeInTheDocument();
  });
});

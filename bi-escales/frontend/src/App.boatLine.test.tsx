/** Brief item A1: the rail says in words where the boat is and when the voyage departs. */
import { render, screen } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as loadVoyage from "./voyage/loadVoyage.js";
import i18n from "./i18n";
import App from "./App";

vi.mock("./hooks/usePledgeQueue", () => ({
  usePledgeQueue: () => ({ pledges: [], loading: false, error: null, needsKey: true, refresh: vi.fn(), updatePledge: vi.fn() }),
}));

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
    fetchSchedule: vi.fn().mockRejectedValue(new Error("no schedule")),
    fetchClock: vi.fn().mockResolvedValue({ start: "2026-11-12", now: "2026-11-16T10:00:00+00:00" }),
    listMilestones: vi.fn().mockResolvedValue([]),
  };
});

const stops = [
  { name: "Saint-Maur (Berry, Indre)", lat: 46.8, lon: 1.6, filmNm: 0, milestoneId: "dep-saint-maur-berry-indre" },
  { name: "La Rochelle", lat: 46.2, lon: -1.2, filmNm: 122.3, milestoneId: "dep-la-rochelle" },
  { name: "Ajaccio (Corse)", lat: 41.9, lon: 8.7, filmNm: 1913.5, milestoneId: "dep-ajaccio-corse" },
];

vi.mock("./voyage/loadVoyage.js", () => ({
  fetchJson: vi.fn().mockResolvedValue({ type: "FeatureCollection", features: [] }),
  sampleAt: vi.fn(),
  voyageFromRoute: vi.fn(() => ({ stops, segments: [], clock: {} })),
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

describe("boat position and departure in the rail", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("says between which stops the boat is, and the departure date", async () => {
    vi.mocked(loadVoyage.sampleAt).mockReturnValue({ status: "live", atQuay: false, filmNm: 563.3, sailNm: 563.3, iso: "2026-11-16T10:00:00.000Z" });
    renderApp();
    expect(await screen.findByTestId("voyage-boat-position")).toHaveTextContent(
      "Boat now: under way, La Rochelle → Ajaccio (Corse)",
    );
    expect(screen.getByTestId("voyage-departure")).toHaveTextContent(/^Departure: 12 Nov 2026$/);
  });

  it("names the stop while the boat is held there", async () => {
    vi.mocked(loadVoyage.sampleAt).mockReturnValue({ status: "live", atQuay: true, filmNm: 1913.5, sailNm: 1913.5, iso: "2026-11-29T03:00:00.000Z" });
    renderApp();
    expect(await screen.findByTestId("voyage-boat-position")).toHaveTextContent("Boat now: at Ajaccio (Corse)");
  });

  it("says in French that the boat waits before departure", async () => {
    await i18n.changeLanguage("fr");
    vi.mocked(loadVoyage.sampleAt).mockReturnValue({ status: "waiting", atQuay: true, countdownHours: 46, filmNm: 0, sailNm: 0, iso: "2026-11-12T08:00:00.000Z" });
    renderApp();
    expect(await screen.findByTestId("voyage-boat-position")).toHaveTextContent(
      "Bateau : Saint-Maur (Berry, Indre), en attente du départ",
    );
    expect(screen.getByTestId("voyage-departure")).toHaveTextContent(/^Départ : 12 nov\. 2026$/);
  });

  it("shows no position line until the boat's position is known", async () => {
    vi.mocked(loadVoyage.sampleAt).mockReturnValue(null);
    renderApp();
    await screen.findByTestId("voyage-clock");
    expect(screen.queryByTestId("voyage-where")).toBeNull();
  });
});

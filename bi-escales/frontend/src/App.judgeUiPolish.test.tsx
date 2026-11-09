import { render, screen, within } from "@testing-library/react";
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

vi.mock("./voyage/loadVoyage.js", () => ({
  fetchJson: vi.fn().mockImplementation(async (path: string) => {
    if (path === "/route.geojson") {
      return {
        type: "FeatureCollection",
        features: [
          {
            type: "Feature",
            geometry: { type: "Point", coordinates: [-1, 46] },
            properties: { name: "La Rochelle", point_type: "escale" },
          },
        ],
      };
    }
    return { type: "FeatureCollection", features: [] };
  }),
  voyageFromRoute: vi.fn(() => ({
    clock: { t0: "2026-11-12T08:00:00.000Z", vertices: [{ tHours: 0, filmNm: 0, sailNm: 0, lat: 46, lon: -1, iso: "2026-11-12T08:00:00.000Z", vehicle: "quay", status: "waiting", countdownHours: 4 }] },
    segments: [],
    stops: [{ name: "La Rochelle", lat: 46, lon: -1, milestoneId: "dep-la-rochelle" }],
  })),
  sampleAt: vi.fn((_clock, when: Date) => ({
    iso: when.toISOString(),
    sailNm: 0,
    lat: 46,
    lon: -1,
    status: "waiting",
    countdownHours: 4,
  })),
}));

vi.mock("./map/MapScene.jsx", () => ({ MapScene: () => <div data-testid="voyage-map" /> }));
vi.mock("./components/EscalePopup.jsx", () => ({
  EscalePopup: ({ stop }: { stop?: { name?: string } }) => (
    <div data-testid="escale-popup">{stop?.name}</div>
  ),
}));
vi.mock("./components/EscalesPanel", () => ({ EscalesPanel: () => <div data-testid="captain-panel" /> }));
vi.mock("./components/ProjectList.jsx", () => ({
  default: () => <div data-testid="project-list" />,
}));
vi.mock("./components/MarinasPanel.jsx", () => ({ default: () => null }));
vi.mock("./components/stop/HowItWorks.jsx", () => ({ HowItWorks: () => <div data-testid="how-it-works" /> }));
vi.mock("./marinas/escaleFiche.js", () => ({
  loadEscaleFiche: vi.fn().mockResolvedValue({ sections: {} }),
  loadEscaleMarinasGeojson: vi.fn().mockResolvedValue({ type: "FeatureCollection", features: [] }),
  loadAllEscalesMarinasGeojson: vi.fn().mockResolvedValue({ type: "FeatureCollection", features: [] }),
  ficheMarinas: vi.fn(() => ({ type: "FeatureCollection", features: [] })),
}));

describe("JUDGE-UI-POLISH", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
    vi.spyOn(escalesApi, "fetchHealthRetrying").mockResolvedValue({ status: "ok" });
    vi.spyOn(escalesApi, "fetchFeatures").mockResolvedValue({ clock_pinned: true, demo_treasurer: false });
    vi.spyOn(escalesApi, "fetchClock").mockResolvedValue({
      start: "2026-11-12T08:00:00.000Z",
      now: "2026-11-12T08:00:00.000Z",
    });
    vi.spyOn(escalesApi, "fetchPublicCommonFund").mockResolvedValue({
      balance_eur: 0,
      currency: "EUR",
      income_eur: 0,
      spending_eur: 0,
    });
    vi.spyOn(escalesApi, "fetchGearProjects").mockResolvedValue({ type: "FeatureCollection", features: [] });
    vi.spyOn(escalesApi, "fetchSchedule").mockResolvedValue({ export: { escales: [] } });
    vi.spyOn(escalesApi, "fetchCrewSupporterPlan").mockResolvedValue({ plan_id: "" });
  });

  it("preselects the demo-clock stop and shows the empty community-fund message", async () => {
    render(
      <I18nextProvider i18n={i18n}>
        <App />
      </I18nextProvider>,
    );

    expect(await screen.findByTestId("escale-popup")).toHaveTextContent("La Rochelle");
    expect(screen.getByTestId("public-common-fund")).toHaveTextContent(/Be the first to give/i);
    expect(escalesApi.fetchClock).toHaveBeenCalled();
  });

  it("keeps the treasurer panel above the collapsed project list", async () => {
    render(
      <I18nextProvider i18n={i18n}>
        <App />
      </I18nextProvider>,
    );

    const sidebar = screen.getByTestId("ng-sidebar");
  const children = Array.from(sidebar.children).map((node) => node.getAttribute("data-testid") || node.className);
    const treasurerIndex = children.findIndex((token) => token.includes("treasurer-panel"));
    const projectsIndex = children.findIndex((token) => token === "project-list");
    expect(treasurerIndex).toBeGreaterThan(-1);
    expect(projectsIndex).toBeGreaterThan(-1);
    expect(treasurerIndex).toBeLessThan(projectsIndex);
    expect(within(sidebar).getByTestId("treasurer-panel")).toBeInTheDocument();
  });
});

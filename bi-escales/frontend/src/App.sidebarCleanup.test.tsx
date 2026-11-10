import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { I18nextProvider } from "react-i18next";
import { beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "./i18n";
import App from "./App";

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
    fetchGearProjects: vi.fn().mockResolvedValue({ type: "FeatureCollection", features: [] }),
    fetchFund: vi.fn().mockResolvedValue({}),
    fetchCrewSupporterPlan: vi.fn().mockResolvedValue({ plan_id: "PLAN-TEST" }),
  };
});

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
          {
            type: "Feature",
            geometry: { type: "Point", coordinates: [8.7, 41.9] },
            properties: { name: "Ajaccio (Corse)", point_type: "escale" },
          },
        ],
      };
    }
    if (path === "/bi-projects.geojson") {
      return {
        type: "FeatureCollection",
        features: [
          {
            type: "Feature",
            geometry: { type: "Point", coordinates: [0, 0] },
            properties: { id: "p1", title: "Ocean project", project_kind: "bi_project" },
          },
          {
            type: "Feature",
            geometry: { type: "Point", coordinates: [1, 1] },
            properties: { id: "g1", title: "Dinghy", project_kind: "gear_project" },
          },
        ],
      };
    }
    return null;
  }),
  sampleAt: vi.fn().mockReturnValue({ iso: "2026-11-12T08:00:00.000Z", sailNm: 0, lat: 46, lon: -1 }),
  voyageFromRoute: vi.fn((_fc: unknown) => ({
    clock: {},
    segments: [],
    stops: [
      { name: "La Rochelle", lat: 46, lon: -1, milestoneId: "dep-la-rochelle" },
      { name: "Ajaccio (Corse)", lat: 41.9, lon: 8.7, milestoneId: "dep-ajaccio-corse" },
    ],
  })),
}));

vi.mock("./map/MapScene.jsx", () => ({ MapScene: () => <div data-testid="voyage-map" /> }));
vi.mock("./components/EscalePopup.jsx", () => ({ EscalePopup: () => null }));
vi.mock("./components/EscalesPanel", () => ({ EscalesPanel: () => <div data-testid="captain-panel" /> }));
vi.mock("./components/MarinasPanel.jsx", () => ({ default: () => <div data-testid="marinas-panel" /> }));
vi.mock("./components/stop/HowItWorks.jsx", () => ({ HowItWorks: () => <div data-testid="how-it-works" /> }));
vi.mock("./components/CrewSubscribeButton", () => ({
  CrewSubscribeButton: () => <span data-testid="crew-button" />,
  CrewSupporterPublicSection: () => (
    <section className="crew-supporter-public" data-testid="crew-supporter-public">
      <span data-testid="crew-button" />
    </section>
  ),
}));
vi.mock("./marinas/escaleFiche.js", () => ({
  loadEscaleFiche: vi.fn(),
  loadEscaleMarinasGeojson: vi.fn().mockResolvedValue({ type: "FeatureCollection", features: [] }),
  loadAllEscalesMarinasGeojson: vi.fn().mockResolvedValue({ type: "FeatureCollection", features: [] }),
  ficheMarinas: vi.fn(() => ({ type: "FeatureCollection", features: [] })),
}));

vi.mock("./components/ProjectList.jsx", () => ({
  default: ({ featureScope }: { featureScope?: string }) => (
    <div data-testid={featureScope === "gear" ? "gear-list" : "project-list"} data-scope={featureScope || "projects"} />
  ),
}));

describe("L-2 sidebar split", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
    document.body.className = "";
  });

  it("keeps features, settings and treasurer on the left and the pledge rail on the right", async () => {
    const user = userEvent.setup();
    render(
      <I18nextProvider i18n={i18n}>
        <App />
      </I18nextProvider>,
    );

    const sidebar = screen.getByTestId("ng-sidebar");
    const pledgeRail = screen.getByTestId("ng-tools-panel");

    expect(within(sidebar).getByTestId("captain-panel")).toBeInTheDocument();
    expect(within(sidebar).getByTestId("crew-supporter-public")).toBeInTheDocument();
    expect(within(sidebar).getByTestId("treasurer-panel")).toBeInTheDocument();
    expect(within(sidebar).getByTestId("theme-switch")).toBeInTheDocument();
    expect(within(sidebar).getByRole("group", { name: "Language" })).toBeInTheDocument();
    expect(within(pledgeRail).queryByTestId("treasurer-panel")).toBeNull();

    // Crew membership and the treasurer entry are secondary: they close the rail, after the Captain.
    const footer = within(sidebar).getByTestId("rail-footer");
    expect(within(footer).getByTestId("crew-supporter-public")).toBeInTheDocument();
    expect(within(footer).getByTestId("treasurer-panel")).toBeInTheDocument();
    expect(
      within(sidebar).getByTestId("captain-panel").compareDocumentPosition(footer)
        & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();

    await user.click(screen.getByRole("tab", { name: /marinas/i }));
    expect(within(sidebar).getByTestId("marinas-panel")).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: /stop/i })).toBeNull();
    expect(screen.queryByText("La Rochelle", { selector: ".stop-picks button" })).toBeNull();
  });

  it("does not repeat the crew subscribe block on the marinas tab", async () => {
    const user = userEvent.setup();
    render(
      <I18nextProvider i18n={i18n}>
        <App />
      </I18nextProvider>,
    );
    expect(screen.getAllByTestId("crew-supporter-public")).toHaveLength(1);
    await user.click(screen.getByRole("tab", { name: /marinas/i }));
    expect(screen.queryByTestId("crew-supporter-public")).toBeNull();
  });

  it("exposes a single treasurer h2 when the panel is expanded", async () => {
    const user = userEvent.setup();
    render(
      <I18nextProvider i18n={i18n}>
        <App />
      </I18nextProvider>,
    );
    await user.click(screen.getByTestId("treasurer-panel-toggle"));
    // Opening the treasurer moves it out of the sidebar into its own full-width page.
    expect(within(screen.getByTestId("ng-sidebar")).queryByTestId("treasurer-panel")).toBeNull();
    const treasurer = within(screen.getByTestId("treasurer-page")).getByTestId("treasurer-panel");
    const treasurerHeadings = within(treasurer).getAllByRole("heading", { level: 2 });
    expect(treasurerHeadings).toHaveLength(1);
    expect(treasurerHeadings[0]).toHaveTextContent(/treasurer/i);
  });
});

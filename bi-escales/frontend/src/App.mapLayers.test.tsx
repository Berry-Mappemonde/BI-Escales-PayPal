import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { I18nextProvider } from "react-i18next";
import { beforeEach, describe, expect, it, vi } from "vitest";
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
    fetchFeatures: vi.fn().mockResolvedValue({}),
    fetchFund: vi.fn().mockResolvedValue({}),
    fetchPublicCommonFund: vi.fn().mockResolvedValue(null),
    fetchGearProjects: vi.fn().mockResolvedValue({ features: [] }),
    fetchPrices: vi.fn().mockRejectedValue(new Error("no prices")),
    fetchSchedule: vi.fn().mockRejectedValue(new Error("no schedule")),
    fetchClock: vi.fn().mockRejectedValue(new Error("no clock")),
    listMilestones: vi.fn().mockResolvedValue([]),
  };
});

const project = { type: "Feature", geometry: { type: "Point", coordinates: [1, 2] }, properties: { id: "p-1", title: "Reef survey" } };
const gear = { type: "Feature", geometry: { type: "Point", coordinates: [3, 4] }, properties: { id: "g-1", title: "Dive computer", project_kind: "gear_project" } };

vi.mock("./voyage/loadVoyage.js", () => ({
  fetchJson: vi.fn(async (path: string) =>
    path.includes("bi-projects") ? { type: "FeatureCollection", features: [project, gear] } : { type: "FeatureCollection", features: [] },
  ),
  sampleAt: vi.fn(() => null),
  voyageFromRoute: vi.fn(() => ({ stops: [], segments: [], clock: {} })),
}));

type SceneProps = { showProjects: boolean; showMarinas: boolean; projects?: { features?: unknown[] }; marinas?: { features?: unknown[] } };

// The scene reports what it was asked to draw, so the test reads the layers the map receives.
vi.mock("./map/MapScene.jsx", () => ({
  MapScene: ({ showProjects, showMarinas, projects, marinas }: SceneProps) => (
    <div
      data-testid="voyage-map"
      data-show-projects={String(showProjects)}
      data-show-marinas={String(showMarinas)}
      data-projects={String(projects?.features?.length ?? 0)}
      data-marinas={String(marinas?.features?.length ?? 0)}
    />
  ),
}));
vi.mock("./components/EscalePopup.jsx", () => ({ EscalePopup: () => null }));
vi.mock("./components/EscalesPanel", () => ({ EscalesPanel: () => null }));
vi.mock("./components/MarinasPanel.jsx", () => ({ default: () => <div data-testid="marinas-panel" /> }));
vi.mock("./components/ProjectList.jsx", () => ({ default: () => null }));
vi.mock("./components/CrewSubscribeButton", () => ({
  CrewSubscribeButton: () => null,
  CrewSupporterPublicSection: () => null,
}));
vi.mock("./marinas/escaleFiche.js", () => ({
  loadEscaleFiche: vi.fn().mockResolvedValue(null),
  loadEscaleMarinasGeojson: vi.fn().mockResolvedValue({ type: "FeatureCollection", features: [] }),
  loadAllEscalesMarinasGeojson: vi.fn().mockResolvedValue({
    type: "FeatureCollection",
    features: [{ type: "Feature", geometry: { type: "Point", coordinates: [-1.15, 46.15] }, properties: { id: "m-1", name: "Bassin des Tamaris" } }],
  }),
  ficheMarinas: vi.fn(() => ({ type: "FeatureCollection", features: [] })),
}));

function renderApp() {
  render(
    <I18nextProvider i18n={i18n}>
      <App />
    </I18nextProvider>,
  );
  const map = () => screen.getByTestId("voyage-map");
  return {
    map,
    projects: screen.getByTestId("map-layer-projects"),
    marinas: screen.getByTestId("map-layer-marinas"),
  };
}

describe("map layers", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
  });

  it("draws projects and marinas together on the Voyage map by default", async () => {
    const { map, projects, marinas } = renderApp();
    expect(projects).toHaveAttribute("aria-pressed", "true");
    expect(marinas).toHaveAttribute("aria-pressed", "true");
    expect(map()).toHaveAttribute("data-show-projects", "true");
    expect(map()).toHaveAttribute("data-show-marinas", "true");
    // Every stop's marinas and the non-gear projects reach the map on this tab.
    await waitFor(() => expect(map()).toHaveAttribute("data-marinas", "1"));
    await waitFor(() => expect(map()).toHaveAttribute("data-projects", "1"));
  });

  it("switches each layer on its own", async () => {
    const user = userEvent.setup();
    const { map, projects, marinas } = renderApp();

    await user.click(projects);
    expect(projects).toHaveAttribute("aria-pressed", "false");
    expect(map()).toHaveAttribute("data-show-projects", "false");
    expect(map()).toHaveAttribute("data-show-marinas", "true");

    await user.click(marinas);
    expect(marinas).toHaveAttribute("aria-pressed", "false");
    expect(map()).toHaveAttribute("data-show-marinas", "false");

    await user.click(projects);
    expect(map()).toHaveAttribute("data-show-projects", "true");
    expect(map()).toHaveAttribute("data-show-marinas", "false");
  });

  it("turns the Marinas layer on when the Marinas tab is selected, and leaves Projects as it was", async () => {
    const user = userEvent.setup();
    const { map, projects, marinas } = renderApp();
    await user.click(marinas);
    await user.click(projects);
    expect(map()).toHaveAttribute("data-show-marinas", "false");

    await user.click(screen.getByRole("tab", { name: /marinas/i }));
    expect(screen.getByTestId("marinas-panel")).toBeInTheDocument();
    expect(marinas).toHaveAttribute("aria-pressed", "true");
    expect(map()).toHaveAttribute("data-show-marinas", "true");
    expect(projects).toHaveAttribute("aria-pressed", "false");
    expect(map()).toHaveAttribute("data-show-projects", "false");
  });

  it("keeps the projects on the map in the Marinas tab while their layer is on, and lets Marinas be switched off there", async () => {
    const user = userEvent.setup();
    const { map, marinas } = renderApp();
    await user.click(screen.getByRole("tab", { name: /marinas/i }));
    await waitFor(() => expect(map()).toHaveAttribute("data-projects", "1"));
    expect(map()).toHaveAttribute("data-show-projects", "true");

    await user.click(marinas);
    expect(map()).toHaveAttribute("data-show-marinas", "false");
    expect(screen.getByTestId("marinas-panel")).toBeInTheDocument();

    // Going back to the Voyage map does not switch anything by itself.
    await user.click(screen.getByRole("tab", { name: /voyage/i }));
    expect(marinas).toHaveAttribute("aria-pressed", "false");
  });
});

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { I18nextProvider } from "react-i18next";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "./i18n";
import App from "./App";
import { isNarrowScreen } from "./utils/narrowScreen";

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
    fetchFund: vi.fn().mockResolvedValue({}),
  };
});

vi.mock("./voyage/loadVoyage.js", () => ({
  fetchJson: vi.fn().mockResolvedValue(null),
  sampleAt: vi.fn(),
  voyageFromRoute: vi.fn(),
}));

const ajaccio = { name: "Ajaccio (Corse)", lat: 41.9, lon: 8.7, milestoneId: "dep-ajaccio-corse" };

vi.mock("./map/MapScene.jsx", () => ({
  MapScene: ({ onSelectStop }: { onSelectStop: (stop: typeof ajaccio) => void }) => (
    <button type="button" data-testid="map-stop" onClick={() => onSelectStop(ajaccio)}>
      stop
    </button>
  ),
}));
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

/** A viewport the way the browser reports it: the query's max-width decides. */
function setViewport(width: number) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: width <= Number(/max-width:\s*([\d.]+)px/.exec(query)?.[1]),
  }));
}

function renderApp() {
  render(
    <I18nextProvider i18n={i18n}>
      <App />
    </I18nextProvider>,
  );
  return {
    sidebar: screen.getByTestId("ng-sidebar"),
    tools: screen.getByTestId("ng-tools-panel"),
    openStop: screen.getByTestId("map-stop"),
    sidebarToggle: screen.getByTestId("ng-sidebar-toggle"),
    toolsToggle: screen.getByTestId("ng-tools-toggle"),
  };
}

describe("opening a stop on a narrow screen", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("collapses the settings panel and moves focus to the stop sheet on the left", async () => {
    setViewport(390);
    const user = userEvent.setup();
    const { sidebar, tools, openStop } = renderApp();
    expect(sidebar.className).not.toMatch(/ng-collapsed/);

    await user.click(openStop);

    expect(await screen.findByTestId("stop-sheet")).toHaveTextContent("Ajaccio (Corse)");
    expect(tools.className).toMatch(/ng-collapsed/);
    await waitFor(() => expect(sidebar).toHaveFocus());
  });

  it("reopens a collapsed left sidebar so the stop sheet is visible", async () => {
    setViewport(390);
    const user = userEvent.setup();
    const { sidebar, openStop, sidebarToggle } = renderApp();
    await user.click(sidebarToggle);
    expect(sidebar.className).toMatch(/ng-collapsed/);

    await user.click(openStop);

    expect(sidebar.className).not.toMatch(/ng-collapsed/);
    await waitFor(() => expect(sidebar).toHaveFocus());
  });

  it("lets the user collapse the sidebar manually while keeping the stop sheet mounted", async () => {
    setViewport(390);
    const user = userEvent.setup();
    const { sidebar, openStop, sidebarToggle } = renderApp();
    await user.click(openStop);

    await user.click(sidebarToggle);
    expect(sidebar.className).toMatch(/ng-collapsed/);
    expect(await screen.findByTestId("stop-sheet")).toBeInTheDocument();

    await user.click(openStop);
    expect(sidebar.className).not.toMatch(/ng-collapsed/);
    await waitFor(() => expect(sidebar).toHaveFocus());
  });

  it("does not touch the panels or focus until a stop is opened", () => {
    setViewport(390);
    const { sidebar } = renderApp();
    expect(sidebar.className).not.toMatch(/ng-collapsed/);
    expect(sidebar).not.toHaveFocus();
  });

  it("reads the width at the moment a stop opens, so rotating counts", async () => {
    setViewport(1024);
    const user = userEvent.setup();
    const { sidebar, openStop } = renderApp();
    await user.click(openStop);
    expect(sidebar.className).not.toMatch(/ng-collapsed/);

    setViewport(390);
    await user.click(openStop);
    expect(sidebar.className).not.toMatch(/ng-collapsed/);
  });
});

describe("opening a stop on a wider screen", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it.each([768, 1280])("keeps both rails open at %ipx", async (width) => {
    setViewport(width);
    const user = userEvent.setup();
    const { sidebar, tools, openStop, toolsToggle } = renderApp();
    await user.click(toolsToggle);

    await user.click(openStop);

    expect(sidebar.className).not.toMatch(/ng-collapsed/);
    expect(tools.className).toMatch(/ng-collapsed/);
    expect(sidebar).not.toHaveFocus();
    expect(openStop).toHaveFocus();
  });
});

describe("isNarrowScreen", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it.each([
    [320, true],
    [767, true],
    [768, false],
    [1280, false],
  ])("at %ipx is %s", (width, narrow) => {
    setViewport(width);
    expect(isNarrowScreen()).toBe(narrow);
  });

  it("is false where matchMedia does not exist", () => {
    vi.stubGlobal("matchMedia", undefined);
    expect(isNarrowScreen()).toBe(false);
  });
});

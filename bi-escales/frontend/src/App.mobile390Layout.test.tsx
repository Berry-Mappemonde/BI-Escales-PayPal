import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { I18nextProvider } from "react-i18next";
import { afterEach, describe, expect, it, vi } from "vitest";
import i18n from "./i18n";
import App from "./App";
import { isMobileToolsSheet } from "./utils/narrowScreen";
import en from "./i18n/locales/en.json";
import fr from "./i18n/locales/fr.json";

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

function setViewport(width: number) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: width <= Number(/max-width:\s*([\d.]+)px/.exec(query)?.[1]),
  }));
}

describe("MOBILE-390 pledge panel bottom sheet", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("uses the mobile sheet layout query at 390px", () => {
    setViewport(390);
    expect(isMobileToolsSheet()).toBe(true);
  });

  it.each([
    ["en", en.app.stopPanelSheetExpand, en.app.stopPanelSheetCollapse],
    ["fr", fr.app.stopPanelSheetExpand, fr.app.stopPanelSheetCollapse],
  ] as const)("toggles collapse and expand labels (%s)", async (language, expandLabel, collapseLabel) => {
    setViewport(390);
    await i18n.changeLanguage(language);
    const user = userEvent.setup();
    render(
      <I18nextProvider i18n={i18n}>
        <App />
      </I18nextProvider>,
    );

    const tools = screen.getByTestId("ng-tools-panel");
    const mapToggle = screen.getByTestId("ng-tools-toggle");
    const handle = screen.getByTestId("ng-tools-sheet-handle");

    expect(mapToggle).toHaveAttribute("aria-label", collapseLabel);
    expect(handle).toHaveAttribute("aria-label", collapseLabel);
    expect(screen.getByText(collapseLabel, { selector: ".ng-tools-sheet-handle-label" })).toBeInTheDocument();

    await user.click(handle);

    expect(tools.className).toMatch(/ng-collapsed/);
    expect(mapToggle).toHaveAttribute("aria-label", expandLabel);

    await user.click(mapToggle);

    expect(tools.className).not.toMatch(/ng-collapsed/);
    expect(mapToggle).toHaveAttribute("aria-label", collapseLabel);
  });

  it("keeps desktop tool toggle copy from 1024px", async () => {
    setViewport(1280);
    await i18n.changeLanguage("en");
    render(
      <I18nextProvider i18n={i18n}>
        <App />
      </I18nextProvider>,
    );

    expect(screen.queryByTestId("ng-tools-sheet-handle")).toBeNull();
    expect(screen.getByTestId("ng-tools-toggle")).toHaveAttribute("aria-label", en.app.toolsCollapse);
  });
});

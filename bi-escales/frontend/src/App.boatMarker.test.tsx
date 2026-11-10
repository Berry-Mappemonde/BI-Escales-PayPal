import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { I18nextProvider } from "react-i18next";
import { beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "./i18n";
import App from "./App";
import * as voyageApi from "./voyage/loadVoyage.js";

const here = dirname(fileURLToPath(import.meta.url));
const routeGeojson = JSON.parse(readFileSync(join(here, "../public/route.geojson"), "utf8"));

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

vi.mock("./components/EscalePopup.jsx", () => ({
  EscalePopup: ({ stop }: { stop?: { name?: string; milestoneId?: string } }) => (
    <div data-testid="stop-sheet">{stop?.name}</div>
  ),
}));
vi.mock("./map/MapScene.jsx", () => ({ MapScene: () => <div data-testid="voyage-map" /> }));
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

vi.mock("./voyage/loadVoyage.js", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./voyage/loadVoyage.js")>();
  return {
    ...actual,
    fetchJson: vi.fn(),
    sampleAt: vi.fn(),
  };
});

describe("App locateBoat chip wiring", () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    await i18n.changeLanguage("en");
    vi.stubGlobal("location", {
      ...window.location,
      hash: "",
      search: "",
      pathname: "/",
      href: "/",
    });

    vi.mocked(voyageApi.fetchJson).mockImplementation(async (path) => {
      if (path === "/route.geojson") return routeGeojson;
      return { type: "FeatureCollection", features: [] };
    });
    vi.mocked(voyageApi.sampleAt).mockReturnValue({
      lat: 46.8075,
      lon: 1.6358,
      status: "waiting",
      bearing: 252.3,
      sailedNm: 0,
    });
  });

  it("chip click and keyboard locate the Saint-Maur boat card before departure", async () => {
    render(
      <I18nextProvider i18n={i18n}>
        <App />
      </I18nextProvider>,
    );

    const chip = await screen.findByRole("button", { name: "Where is the boat?" });
    fireEvent.click(chip);
    await waitFor(() =>
      expect(screen.getByTestId("stop-sheet")).toHaveTextContent("Saint-Maur (Berry, Indre)"),
    );

    chip.focus();
    await userEvent.keyboard("{Enter}");
    await waitFor(() =>
      expect(screen.getByTestId("stop-sheet")).toHaveTextContent("Saint-Maur (Berry, Indre)"),
    );
  });
});

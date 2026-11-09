import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { I18nextProvider } from "react-i18next";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import i18n from "../i18n";

const AXE_RULES = ["button-name", "link-name", "label-content-name-mismatch"] as const;

vi.mock("../hooks/usePledgeQueue", () => ({
  usePledgeQueue: () => ({
    pledges: [],
    loading: false,
    error: null,
    needsKey: true,
    refresh: vi.fn(),
    updatePledge: vi.fn(),
  }),
}));

vi.mock("../api/escales", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/escales")>();
  return {
    ...actual,
    fetchHealthRetrying: vi.fn().mockResolvedValue({ status: "ok" }),
    fetchFeatures: vi.fn().mockResolvedValue({ clock_pinned: false }),
    authorizePledge: vi.fn(),
    registerVault: vi.fn(),
    fetchFund: vi.fn().mockResolvedValue({
      balance_eur: "0.00",
      currency: "EUR",
      income_eur: "0.00",
      spending_eur: "0.00",
    }),
    settleClock: vi.fn(),
  };
});

vi.mock("../voyage/loadVoyage.js", () => ({
  fetchJson: vi.fn().mockResolvedValue(null),
  sampleAt: vi.fn(),
  voyageFromRoute: vi.fn(),
}));

vi.mock("../map/MapScene.jsx", () => ({ MapScene: () => <div data-testid="voyage-map" /> }));
vi.mock("../components/EscalePopup.jsx", () => ({ EscalePopup: () => null }));
vi.mock("../components/EscalesPanel", () => ({ EscalesPanel: () => <div data-testid="captain-panel" /> }));
vi.mock("../components/MarinasPanel.jsx", () => ({ default: () => <div data-testid="marinas-panel" /> }));
vi.mock("../components/ProjectList.jsx", () => ({ default: () => null }));
vi.mock("../components/CrewSubscribeButton", () => ({
  CrewSubscribeButton: () => <span>Crew</span>,
  CrewSupporterPublicSection: () => (
    <section className="crew-supporter-public" data-testid="crew-supporter-public">
      <span>Crew</span>
    </section>
  ),
}));
vi.mock("../marinas/escaleFiche.js", () => ({
  loadEscaleFiche: vi.fn(),
  loadEscaleMarinasGeojson: vi.fn().mockResolvedValue({ type: "FeatureCollection", features: [] }),
  loadAllEscalesMarinasGeojson: vi.fn().mockResolvedValue({ type: "FeatureCollection", features: [] }),
  ficheMarinas: vi.fn(() => ({ type: "FeatureCollection", features: [] })),
}));

function runAxe(element: HTMLElement) {
  return new Promise<axe.AxeResults>((resolve, reject) => {
    axe.run(
      element,
      {
        runOnly: { type: "rule", values: [...AXE_RULES] },
      },
      (err, results) => {
        if (err) reject(err);
        else resolve(results!);
      },
    );
  });
}

describe("axe shell controls (SITE-A11Y-2)", () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    await i18n.changeLanguage("en");
    vi.stubGlobal("location", {
      ...window.location,
      hash: "",
      search: "",
      pathname: "/",
      href: "http://localhost/",
    });
    document.body.className = "";
  });

  it("reports no button-name, link-name, or label-content-name-mismatch in shell controls", async () => {
  const user = userEvent.setup();
    render(
      <I18nextProvider i18n={i18n}>
        <App />
      </I18nextProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("voyage-map")).toBeInTheDocument());
    await user.click(screen.getByTestId("ng-tools-toggle"));

    const results = await runAxe(document.body);
    const violations = results.violations.filter((v) => AXE_RULES.includes(v.id as (typeof AXE_RULES)[number]));

    expect(violations).toEqual([]);
  });
});

import { render, screen, within } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "./index";
import en from "./locales/en.json";
import fr from "./locales/fr.json";
import App from "../App";
import { TreasurerPanel } from "../components/TreasurerPanel";

const OLD_TAGLINE_EN = /Pay Only If We Sail/i;
const OLD_TAGLINE_FR = /Payez seulement si nous partons/i;

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
    fetchFeatures: vi.fn().mockResolvedValue({ clock_pinned: false, demo_treasurer: true }),
    fetchFund: vi.fn().mockResolvedValue({
      balance_eur: "0.00",
      currency: "EUR",
      income_eur: "0.00",
      spending_eur: "0.00",
    }),
  };
});

vi.mock("../voyage/loadVoyage.js", () => ({
  fetchJson: vi.fn().mockResolvedValue(null),
  sampleAt: vi.fn(),
  voyageFromRoute: vi.fn(),
}));

vi.mock("../map/MapScene.jsx", () => ({ MapScene: () => <div data-testid="voyage-map" /> }));
vi.mock("../components/EscalePopup.jsx", () => ({ EscalePopup: () => null }));
vi.mock("../components/EscalesPanel", () => ({ EscalesPanel: () => null }));
vi.mock("../components/MarinasPanel.jsx", () => ({ default: () => null }));
vi.mock("../components/ProjectList.jsx", () => ({ default: () => null }));
vi.mock("../components/stop/HowItWorks.jsx", () => ({ HowItWorks: () => <div data-testid="how-it-works" /> }));
vi.mock("../components/CrewSubscribeButton", () => ({
  CrewSubscribeButton: () => null,
  CrewSupporterPublicSection: () => null,
}));
vi.mock("../marinas/escaleFiche.js", () => ({
  loadEscaleFiche: vi.fn(),
  loadEscaleMarinasGeojson: vi.fn().mockResolvedValue({ type: "FeatureCollection", features: [] }),
  loadAllEscalesMarinasGeojson: vi.fn().mockResolvedValue({ type: "FeatureCollection", features: [] }),
  ficheMarinas: vi.fn(() => ({ type: "FeatureCollection", features: [] })),
}));

describe("DESIGN-P1-HEADER-SETTINGS tagline", () => {
  it("ships stop-arrival taglines in locale bundles without the old sail copy", () => {
    expect(en.app.subtitle).toBe("Pay only when we arrive");
    expect(fr.app.subtitle).toBe("Payez seulement à notre arrivée");
    expect(JSON.stringify(en)).not.toMatch(OLD_TAGLINE_EN);
    expect(JSON.stringify(fr)).not.toMatch(OLD_TAGLINE_FR);
  });

  it("renders the new subtitle in the sidebar header (EN and FR)", async () => {
    const { rerender } = render(
      <I18nextProvider i18n={i18n}>
        <App />
      </I18nextProvider>,
    );

    await i18n.changeLanguage("en");
    rerender(
      <I18nextProvider i18n={i18n}>
        <App />
      </I18nextProvider>,
    );
    const sidebarEn = screen.getByTestId("ng-sidebar");
    expect(within(sidebarEn).getByText(en.app.subtitle)).toBeInTheDocument();
    expect(within(sidebarEn).queryByText(OLD_TAGLINE_EN)).toBeNull();

    await i18n.changeLanguage("fr");
    rerender(
      <I18nextProvider i18n={i18n}>
        <App />
      </I18nextProvider>,
    );
    expect(within(sidebarEn).getByText(fr.app.subtitle)).toBeInTheDocument();
    expect(within(sidebarEn).queryByText(OLD_TAGLINE_FR)).toBeNull();
  });
});

describe("DESIGN-P1-HEADER-SETTINGS settings panel", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
  });

  it("does not duplicate the header theme toggle in the settings rail", () => {
    render(
      <I18nextProvider i18n={i18n}>
        <App />
      </I18nextProvider>,
    );
    const settings = within(screen.getByTestId("ng-settings-body"));
    expect(settings.queryByTestId("theme-toggle")).toBeNull();
    expect(settings.queryByTestId("theme-switch")).toBeNull();
    expect(within(screen.getByTestId("ng-sidebar")).getByTestId("theme-toggle")).toBeInTheDocument();
  });

  it("exposes language controls only inside the settings panel", () => {
    render(
      <I18nextProvider i18n={i18n}>
        <App />
      </I18nextProvider>,
    );
    const sidebar = screen.getByTestId("ng-sidebar");
    expect(within(sidebar).queryByRole("group", { name: "Language" })).toBeNull();
    expect(within(screen.getByTestId("ng-settings-controls")).getByRole("group", { name: "Language" })).toBeInTheDocument();
  });
});

const treasurerBase = {
  open: false,
  onOpenChange: vi.fn(),
  adminKey: "",
  onAdminKeyChange: vi.fn(),
  settleBusy: false,
  settleNote: null,
  onSettle: vi.fn(),
  clockPinned: false,
  settleAt: "",
  onSettleAtChange: vi.fn(),
  onSettleAt: vi.fn(),
  milestoneId: "dep-la-rochelle",
  onMilestoneIdChange: vi.fn(),
  projectFund: null,
  boatFund: null,
  pledges: [],
  loading: false,
  error: null,
  needsKey: true,
  onRefreshQueue: vi.fn(),
  onPledgeUpdated: vi.fn(),
  spendAmount: "",
  onSpendAmountChange: vi.fn(),
  spendNote: "",
  onSpendNoteChange: vi.fn(),
  spendError: null,
  fund: null,
  onSpendSubmit: vi.fn((event) => event.preventDefault()),
};

describe("DESIGN-P1-HEADER-SETTINGS stop sheet and crew copy", () => {
  it("uses arrival-based payment rules instead of sail wording in locale bundles", () => {
    expect(en.stopPanel.paymentRuleStop).toMatch(/arriv/i);
    expect(en.stopPanel.paymentRuleStop).toMatch(/cancel/i);
    expect(en.stopPanel.paymentRuleStop).not.toMatch(/don't sail|only if we sail/i);
    expect(fr.stopPanel.paymentRuleStop).toMatch(/arrivée/i);
    expect(fr.stopPanel.paymentRuleStop).not.toMatch(/si nous partons/i);
    expect(en.howItWorks.heading).toContain("Pay only when we arrive");
    expect(en.howItWorks.heading).not.toMatch(/Pay only if we arrive/i);
    expect(fr.howItWorks.heading).toContain("Payez seulement à notre arrivée");
  });

  it("names the crew product Abonnement Crew in EN and FR", () => {
    expect(en.pledge.crewSubscribeProduct).toBe("Abonnement Crew");
    expect(fr.pledge.crewSubscribeProduct).toBe("Abonnement Crew");
    expect(en.pledge.crewSubscribeLoading).toMatch(/Abonnement Crew/i);
    expect(en.pledge.crewSubscribeLoading).not.toMatch(/Crew supporter/i);
  });
});

describe("DESIGN-P1-HEADER-SETTINGS treasurer heading", () => {
  it("keeps the French panel title visible with the demo entry stacked below", async () => {
    await i18n.changeLanguage("fr");
    render(
      <I18nextProvider i18n={i18n}>
        <TreasurerPanel
          {...treasurerBase}
          demoStopAvailable
        >
          <button type="button" data-testid="demo-treasurer-button">
            {fr.treasurer.demoButton}
          </button>
        </TreasurerPanel>
      </I18nextProvider>,
    );
    const heading = screen.getByTestId("treasurer-panel-heading");
    expect(within(heading).getByRole("heading", { level: 2, name: fr.treasurer.panelTitle })).toBeVisible();
    expect(within(heading).getByTestId("demo-treasurer-button")).toBeInTheDocument();
  });

  it("shows the English panel title without clipping in the sidebar rail", async () => {
    await i18n.changeLanguage("en");
    render(
      <I18nextProvider i18n={i18n}>
        <App />
      </I18nextProvider>,
    );
    const treasurerHeading = within(screen.getByTestId("treasurer-panel")).getByTestId("treasurer-panel-heading");
    expect(within(treasurerHeading).getByRole("heading", { level: 2, name: en.treasurer.panelTitle })).toBeVisible();
  });
});

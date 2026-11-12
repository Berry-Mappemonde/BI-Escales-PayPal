import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { I18nextProvider } from "react-i18next";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import i18n from "../i18n";

// label-content-name-mismatch never fires under jsdom (axe needs layout it does not have):
// it stays listed for a real browser, and labelsMissingTheirText below is what checks it here.
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
    fetchPublicCommonFund: vi.fn().mockResolvedValue({ balance_eur: "45.00", currency: "EUR" }),
    fetchGearProjects: vi.fn().mockResolvedValue({ features: [] }),
    fetchPrices: vi.fn().mockRejectedValue(new Error("no prices")),
    fetchSchedule: vi.fn().mockRejectedValue(new Error("no schedule")),
    fetchClock: vi.fn().mockResolvedValue({ start: "2026-11-12", now: "2026-11-12T10:00:00+00:00" }),
    listMilestones: vi.fn().mockResolvedValue([]),
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

/**
 * WCAG 2.5.3 (label in name), checked directly: axe's own rule needs a real
 * layout to know which text is visible, and reports nothing under jsdom.
 * Returns the controls whose aria-label does not start with their visible text (WCAG 2.5.3, best practice).
 */
function labelsMissingTheirText(root: HTMLElement): string[] {
  const squash = (text: string) => text.replace(/\s+/g, " ").trim().toLowerCase();
  return [...root.querySelectorAll<HTMLElement>("button[aria-label], a[aria-label], [role='button'][aria-label]")]
    .filter((control) => {
      const text = squash(
        [...control.childNodes]
          .filter((node) => !(node instanceof Element && node.getAttribute("aria-hidden") === "true"))
          .map((node) => node.textContent ?? "")
          .join(" "),
      );
      // Symbols alone (an arrow, a dot) are not a spoken label.
      if (!/[\p{L}\p{N}]/u.test(text)) return false;
      return !squash(control.getAttribute("aria-label") ?? "").startsWith(text);
    })
    .map((control) => control.outerHTML.slice(0, 160));
}

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

    expect(violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.html).join(" | ")}`)).toEqual([]);
    expect(labelsMissingTheirText(document.body)).toEqual([]);

    // The language buttons were the mismatch in the audit: the label now starts with the visible text.
    expect(screen.getByRole("button", { name: "FR, Français" })).toHaveTextContent("FR");
    expect(screen.getByRole("button", { name: "EN, English" })).toHaveTextContent("EN");
  });

  it("finds a control without a name, so an empty result means something", async () => {
    document.body.innerHTML =
      '<button type="button"></button><a href="/x"></a><button type="button" aria-label="Close">Open</button>' +
      '<button type="button" aria-label="FR, Français">FR</button><a href="/y" aria-label="Google Maps">◎</a>' +
      '<button type="button" aria-label="Switch to FR">FR</button>';
    const results = await runAxe(document.body);
    expect(results.violations.map((v) => v.id).sort()).toEqual(["button-name", "link-name"]);
    expect(labelsMissingTheirText(document.body)).toEqual([
      '<button type="button" aria-label="Close">Open</button>',
      // Contains the visible text but does not start with it.
      '<button type="button" aria-label="Switch to FR">FR</button>',
    ]);
    document.body.innerHTML = "";
  });
});

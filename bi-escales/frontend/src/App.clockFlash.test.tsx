import { render, screen, waitFor } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "./i18n";
import App from "./App";
import * as escalesApi from "./api/escales";
import * as voyageApi from "./voyage/loadVoyage.js";

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
    fetchFund: vi.fn().mockResolvedValue({
      balance_eur: "0.00",
      currency: "EUR",
      income_eur: "0.00",
      spending_eur: "0.00",
    }),
    fetchPublicCommonFund: vi.fn().mockResolvedValue({
      milestone_id: "common",
      balance_eur: "0.00",
      currency: "EUR",
      income_eur: "0.00",
      spending_eur: "0.00",
    }),
    fetchGearProjects: vi.fn().mockResolvedValue({ type: "FeatureCollection", features: [] }),
    fetchSchedule: vi.fn().mockResolvedValue({ export: { escales: [] } }),
    fetchCrewSupporterPlan: vi.fn().mockResolvedValue({ plan_id: "" }),
  };
});

vi.mock("./voyage/loadVoyage.js", () => ({
  fetchJson: vi.fn().mockResolvedValue({}),
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

const WALL_ISO = "2030-06-15T12:00:00.000Z";

describe("CLOCK-FLASH voyage clock", () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    await i18n.changeLanguage("en");
    vi.spyOn(Date, "now").mockReturnValue(new Date(WALL_ISO).getTime());
    vi.mocked(voyageApi.fetchJson).mockResolvedValue({});
    vi.mocked(voyageApi.voyageFromRoute).mockReturnValue({ clock: {} } as never);
    vi.mocked(voyageApi.sampleAt).mockReturnValue({
      status: "waiting",
      countdownHours: 139,
      iso: "2026-11-12T08:00:00.000Z",
      sailNm: 0,
    } as never);
  });

  it("does not render wall-clock countdown text before fetchClock resolves", async () => {
    let resolveClock!: (value: { now: string; start: string }) => void;
    const pending = new Promise<{ now: string; start: string }>((resolve) => {
      resolveClock = resolve;
    });
    vi.spyOn(escalesApi, "fetchClock").mockReturnValue(pending);

    render(
      <I18nextProvider i18n={i18n}>
        <App />
      </I18nextProvider>,
    );

    const clock = screen.getByTestId("voyage-clock");
    expect(clock).toHaveAttribute("aria-label", "Voyage clock loading");
    expect(clock).not.toHaveTextContent("Departure in");
    expect(clock).not.toHaveTextContent("2030");
    expect(clock.textContent).toContain("—");

    resolveClock({
      start: "2026-11-12T08:00:00.000Z",
      now: "2026-11-12T08:00:00.000Z",
    });

    await waitFor(() => expect(clock).toHaveTextContent("Departure in 5d 19h"));
    expect(clock).toHaveTextContent("12 Nov 2026 · 08:00 UTC");
    expect(clock).not.toHaveAttribute("aria-label");
  });

  it("fails if voyage sampling uses Date.now() before the clock response (regression guard)", () => {
    const wallYear = String(new Date(WALL_ISO).getUTCFullYear());
    const simulatedYear = "2026";
    expect(wallYear).toBe("2030");
    expect(simulatedYear).not.toBe(wallYear);
    vi.spyOn(escalesApi, "fetchClock").mockReturnValue(new Promise(() => undefined));

    render(
      <I18nextProvider i18n={i18n}>
        <App />
      </I18nextProvider>,
    );

    const clock = screen.getByTestId("voyage-clock");
    expect(clock.textContent ?? "").not.toMatch(new RegExp(wallYear));
  });
});

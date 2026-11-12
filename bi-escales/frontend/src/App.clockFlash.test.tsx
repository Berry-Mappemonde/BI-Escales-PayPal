/**
 * The voyage clock shows nothing computed from the browser's time while the
 * first clock request is on its way (CLOCK-FLASH, ported from #201).
 */
import { act, render, screen, waitFor } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as escalesApi from "./api/escales";
import * as loadVoyage from "./voyage/loadVoyage.js";
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
    fetchFeatures: vi.fn().mockResolvedValue({ clock_pinned: true }),
    fetchFund: vi.fn().mockResolvedValue({}),
    fetchPublicCommonFund: vi.fn().mockResolvedValue(null),
    fetchGearProjects: vi.fn().mockResolvedValue({ features: [] }),
    fetchPrices: vi.fn().mockRejectedValue(new Error("no prices")),
    fetchSchedule: vi.fn().mockRejectedValue(new Error("no schedule")),
    fetchClock: vi.fn(),
    listMilestones: vi.fn().mockResolvedValue([]),
  };
});

const stops = [{ name: "La Rochelle", lat: 46.2, lon: -1.2, milestoneId: "dep-la-rochelle" }];

vi.mock("./voyage/loadVoyage.js", () => ({
  fetchJson: vi.fn().mockResolvedValue({ type: "FeatureCollection", features: [] }),
  // The sample echoes the instant it was asked for, so the test sees which clock was used.
  sampleAt: vi.fn((_clock: unknown, when: Date) => ({ status: "sailing", iso: when.toISOString(), sailNm: 131.3 })),
  voyageFromRoute: vi.fn(() => ({ stops, segments: [], clock: {} })),
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
  loadEscaleFiche: vi.fn().mockResolvedValue(null),
  loadEscaleMarinasGeojson: vi.fn().mockResolvedValue({ type: "FeatureCollection", features: [] }),
  loadAllEscalesMarinasGeojson: vi.fn().mockResolvedValue({ type: "FeatureCollection", features: [] }),
  ficheMarinas: vi.fn(() => ({ type: "FeatureCollection", features: [] })),
}));

function renderApp() {
  render(
    <I18nextProvider i18n={i18n}>
      <App />
    </I18nextProvider>,
  );
}

/** The year the browser believes it is, far from the voyage, so a leak is easy to see. */
const WALL = new Date("2030-06-15T12:00:00.000Z");

describe("voyage clock before the API clock answers", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
    vi.useFakeTimers({ now: WALL, toFake: ["Date"] });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it("shows a placeholder, then the API's time, and never the browser's", async () => {
    let answer: (clock: { start: string; now: string }) => void = () => undefined;
    vi.mocked(escalesApi.fetchClock).mockReturnValue(new Promise((resolve) => { answer = resolve; }) as never);
    renderApp();

    const clock = await screen.findByTestId("voyage-clock");
    await waitFor(() => expect(loadVoyage.voyageFromRoute).toHaveBeenCalled());
    expect(clock).toHaveAttribute("aria-busy", "true");
    expect(clock).toHaveAccessibleName("Voyage clock loading");
    expect(clock).toHaveTextContent("—");
    expect(clock).not.toHaveTextContent("2030");
    expect(clock).not.toHaveTextContent("nm sailed");
    expect(loadVoyage.sampleAt).not.toHaveBeenCalled();

    await act(async () => {
      answer({ start: "2026-11-12", now: "2026-11-12T10:00:00+00:00" });
    });
    await waitFor(() => expect(clock).toHaveTextContent("12 Nov 2026 · 10:00 UTC"));
    expect(clock).toHaveTextContent("131.3 nm sailed · Demo clock");
    expect(clock).not.toHaveAttribute("aria-busy");
    expect(clock).not.toHaveAttribute("aria-label");
    expect(clock).not.toHaveTextContent("2030");
  });

  it("names the placeholder in French too", async () => {
    await i18n.changeLanguage("fr");
    vi.mocked(escalesApi.fetchClock).mockReturnValue(new Promise(() => undefined) as never);
    renderApp();
    expect(await screen.findByTestId("voyage-clock")).toHaveAccessibleName("Chargement de l’horloge du voyage");
  });

  it("falls back to the browser's time only once the clock request has failed", async () => {
    vi.mocked(escalesApi.fetchClock).mockRejectedValue(new Error("clock down"));
    renderApp();
    const clock = await screen.findByTestId("voyage-clock");
    await waitFor(() => expect(clock).toHaveTextContent("15 Jun 2030"));
    expect(clock).not.toHaveAttribute("aria-busy");
  });

  it("asks the clock again soon after a failure, and the API's time then replaces the browser's", async () => {
    const setTimeoutSpy = vi.spyOn(window, "setTimeout");
    vi.mocked(escalesApi.fetchClock)
      .mockRejectedValueOnce(new Error("Clock request timed out after 12000 ms"))
      .mockResolvedValue({ start: "2026-11-12", now: "2026-11-12T10:00:00+00:00" });
    renderApp();
    const clock = await screen.findByTestId("voyage-clock");
    await waitFor(() => expect(clock).toHaveTextContent("15 Jun 2030"));

    // The retry is scheduled well before the regular one-minute re-sync.
    const retry = setTimeoutSpy.mock.calls.find(([, delay]) => delay === 10000);
    expect(retry).toBeDefined();
    await act(async () => {
      (retry![0] as () => void)();
    });
    await waitFor(() => expect(clock).toHaveTextContent("12 Nov 2026 · 10:00 UTC"));
    expect(clock).not.toHaveTextContent("2030");
    setTimeoutSpy.mockRestore();
  });

  it("does not name a next stop from the browser's time", async () => {
    vi.mocked(escalesApi.fetchClock).mockReturnValue(new Promise(() => undefined) as never);
    renderApp();
    // The schedule request has failed, so only the clock is still awaited.
    const button = await screen.findByTestId("back-next-stop-pending");
    await waitFor(() => expect(loadVoyage.voyageFromRoute).toHaveBeenCalled());
    expect(button).toBeDisabled();
    expect(button).not.toHaveTextContent("La Rochelle");
    expect(screen.queryByTestId("back-next-stop")).toBeNull();
  });
});

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { I18nextProvider } from "react-i18next";
import { beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "./i18n";
import App from "./App";

const queued = vi.hoisted(() => ({ pledges: [] as unknown[] }));
const flags = vi.hoisted(() => ({ bryntum: true }));
const calendars = vi.hoisted(() => ({ props: [] as Array<Record<string, unknown>> }));

vi.mock("./components/escales/EscalesScheduler.jsx", () => ({
  default: (props: Record<string, unknown>) => {
    calendars.props.push(props);
    return (
      <section data-testid="stopover-calendar" data-wide={String(Boolean(props.wide))} data-cabins={String(props.showCabins !== false)} />
    );
  },
}));

vi.mock("./hooks/usePledgeQueue", () => ({
  usePledgeQueue: (_adminKey: string, demoTreasurer?: boolean) => ({
    pledges: demoTreasurer ? queued.pledges : [],
    loading: false,
    error: null,
    needsKey: !demoTreasurer,
    refresh: vi.fn(),
    updatePledge: vi.fn(),
  }),
}));

vi.mock("./api/escales", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./api/escales")>();
  return {
    ...actual,
    fetchHealthRetrying: vi.fn().mockResolvedValue({ status: "ok" }),
    fetchFeatures: vi.fn(async () => ({ clock_pinned: false, demo_treasurer: true, bryntum: flags.bryntum })),
    fetchSchedule: vi.fn(async () => ({
      export: { escales: [{ milestone_id: "dep-la-rochelle", name: "La Rochelle", arrival_iso: "2026-11-12T12:00:00Z" }] },
      legs: [{ id: "leg-la-rochelle-to-ajaccio-corse", from_name: "La Rochelle", to_name: "Ajaccio (Corse)" }],
    })),
    fetchFund: vi.fn().mockResolvedValue({
      balance_eur: "0.00",
      currency: "EUR",
      income_eur: "0.00",
      spending_eur: "0.00",
    }),
    listPledges: vi.fn().mockResolvedValue([]),
  };
});

vi.mock("./voyage/loadVoyage.js", () => ({
  fetchJson: vi.fn().mockResolvedValue({ type: "FeatureCollection", features: [] }),
  sampleAt: vi.fn(() => null),
  voyageFromRoute: vi.fn(() => ({
    stops: [
      { name: "La Rochelle", lat: 46.16, lon: -1.15, milestoneId: "dep-la-rochelle" },
      { name: "Ajaccio (Corse)", lat: 41.92, lon: 8.73, milestoneId: "dep-ajaccio-corse" },
    ],
    segments: [],
    clock: {},
  })),
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

/** A2 / B3: where the stopover calendar is shown when features.bryntum is on. */
describe("Stopover calendar placement", () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    queued.pledges = [];
    calendars.props.length = 0;
    flags.bryntum = true;
    await i18n.changeLanguage("en");
    vi.stubGlobal("location", { ...window.location, hash: "", search: "", pathname: "/", href: "http://localhost/" });
    vi.stubGlobal("history", { ...window.history, replaceState: vi.fn() });
  });

  function renderApp() {
    render(
      <I18nextProvider i18n={i18n}>
        <App />
      </I18nextProvider>,
    );
  }

  it("flag on: the visitor's rail has the calendar, with the cabins and a way to open a stop", async () => {
    renderApp();
    const calendar = await screen.findByTestId("stopover-calendar");
    expect(calendar.closest('[data-testid="ng-sidebar"]')).not.toBeNull();
    expect(calendar).toHaveAttribute("data-wide", "false");
    expect(calendar).toHaveAttribute("data-cabins", "true");
    expect(calendars.props.at(-1)?.onSelectEscale).toEqual(expect.any(Function));
    expect(calendars.props.at(-1)?.planningEnabled).toBe(true);
  });

  it("flag on: the treasurer page has it too, wide, read-only and without the cabin checkouts", async () => {
    const user = userEvent.setup();
    renderApp();
    await screen.findByTestId("stopover-calendar");
    await user.click(await screen.findByTestId("demo-treasurer-button"));
    const page = screen.getByTestId("treasurer-page");
    const calendar = await within(page).findByTestId("stopover-calendar");
    expect(calendar).toHaveAttribute("data-wide", "true");
    expect(calendar).toHaveAttribute("data-cabins", "false");
    // Above the treasurer's tools, not inside them.
    expect(calendar.closest(".treasurer-panel")).toBeNull();
    const inPage = calendars.props.filter((props) => props.wide === true).at(-1);
    expect(inPage?.onSelectEscale).toBeUndefined();
    expect(inPage?.onAuthorized).toBeUndefined();
    // The treasurer's copy knows each stop's status and held pledges; the visitor's does not.
    expect(inPage?.stopOverview).toMatchObject({ "dep-la-rochelle": { held: 0, due: false } });
    expect(calendars.props.filter((props) => props.wide !== true).every((props) => props.stopOverview === undefined)).toBe(true);
  });

  it("flag off: no calendar anywhere", async () => {
    flags.bryntum = false;
    const user = userEvent.setup();
    renderApp();
    await user.click(await screen.findByTestId("demo-treasurer-button"));
    await waitFor(() => expect(screen.getByTestId("demo-treasurer-banner")).toBeInTheDocument());
    expect(screen.queryByTestId("stopover-calendar")).toBeNull();
    expect(calendars.props).toHaveLength(0);
  });
});

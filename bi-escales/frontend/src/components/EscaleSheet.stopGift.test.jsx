import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fetchClock, fetchFund, listMilestones } from "../api/escales";
import i18n from "../i18n";
import { EscaleSheet } from "./EscaleSheet.jsx";

vi.mock("../api/escales", () => ({
  fetchClock: vi.fn(),
  fetchFund: vi.fn(),
  listMilestones: vi.fn(),
}));

const buttonProps = [];
vi.mock("./PledgeButton", () => ({
  PledgeButton: (props) => {
    buttonProps.push(props);
    return <div data-testid="pledge-values">{JSON.stringify(props.values)}</div>;
  },
}));

const STOP_ID = "dep-ajaccio-corse";
const ARRIVAL = "2026-11-28T22:02:54.002Z";
const LEAVES = "2026-12-01T22:02:54.002Z";
const stop = { name: "Ajaccio (Corse)", lat: 41.9, lon: 8.7, milestoneId: STOP_ID };
const schedule = {
  export: {
    escales: [
      { milestone_id: "dep-la-rochelle", name: "La Rochelle", arrival_iso: "2026-11-12T08:00:00.000Z" },
      { milestone_id: STOP_ID, name: "Ajaccio (Corse)", arrival_iso: ARRIVAL },
    ],
  },
  legs: [
    {
      id: "leg-la-rochelle-to-ajaccio-corse",
      from_name: "La Rochelle",
      to_name: "Ajaccio (Corse)",
      departure_iso: "2026-11-12T08:00:00.000Z",
      arrival_iso: ARRIVAL,
    },
    {
      id: "leg-ajaccio-corse-to-fort-de-france-martinique",
      from_name: "Ajaccio (Corse)",
      to_name: "Fort-de-France (Martinique)",
      departure_iso: LEAVES,
    },
  ],
};
const logbook = [
  { t: "2026-11-26T22:02:54Z", pos: { lat: 42.1, lon: 7.9 }, label_en: "Position — underway for Ajaccio", label_fr: "Position — en route vers Ajaccio" },
  { t: ARRIVAL, pos: { lat: 41.9, lon: 8.7 }, label_en: "Stopover — arrival at Ajaccio", label_fr: "Escale — arrivée Ajaccio" },
];
const pledge = (kind = "mile", amount = "20") => ({
  amount,
  milestoneId: STOP_ID,
  contributor: "",
  kind,
  onAmount: () => {},
  onMilestoneId: () => {},
  onContributor: () => {},
  onKind: () => {},
});

function tree(props = {}) {
  return (
    <I18nextProvider i18n={i18n}>
      <EscaleSheet
        stop={stop}
        fiche={null}
        schedule={schedule}
        arrivalIso={ARRIVAL}
        logbookEntries={logbook}
        pledge={pledge()}
        onPledgeAuthorized={() => {}}
        {...props}
      />
    </I18nextProvider>
  );
}

async function show(props) {
  render(tree(props));
  await waitFor(() => expect(fetchFund).toHaveBeenCalled());
  await act(async () => {});
}

/** The third stop fund (#267): a free-amount gift held until the boat arrives. */
describe("gift to a stop", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
    buttonProps.length = 0;
    vi.mocked(fetchClock).mockReset().mockResolvedValue({ now: "2026-11-20T08:00:00+00:00" });
    vi.mocked(listMilestones).mockReset().mockResolvedValue([{ id: STOP_ID, evidence: [] }]);
    vi.mocked(fetchFund).mockReset().mockResolvedValue({ authorized_eur: "0.00", captured_eur: "0.00" });
  });

  afterEach(cleanup);

  it("is its own option, apart from the common fund charged at once", async () => {
    await show();
    const options = within(screen.getByTestId("pledge-kind")).getAllByRole("option");
    const labels = options.map((option) => option.textContent);
    expect(labels).toContain("Gift to this stop (held until arrival)");
    expect(labels).toContain("Common fund (charged immediately)");
    expect(options.find((option) => option.value === "stop_gift")).toBeDefined();
  });

  it("sends kind stop_gift for this stop, with the amount the supporter typed", async () => {
    await show({ pledge: pledge("stop_gift", "17.35") });
    const values = buttonProps.at(-1).values;
    expect(values).toMatchObject({
      kind: "stop_gift",
      amount_eur: "17.35",
      milestone_id: STOP_ID,
      target_id: STOP_ID,
      description: "Ajaccio (Corse) — Gift to this stop (held until arrival)",
    });
    expect(values.quantity).toBeUndefined();
    expect(screen.getByTestId("pledge-amount")).not.toHaveAttribute("readonly");
  });

  it("explains it is held, captured on arrival, released on cancellation, unlike the common fund", async () => {
    await show({ pledge: pledge("stop_gift", "25") });
    expect(screen.getByTestId("stop-gift-note")).toHaveTextContent(
      "Choose any amount up to €1,000. Unlike the common fund, nothing is charged today: the gift is held for this stop, captured when the boat arrives, and released if the stop is cancelled.",
    );
    const rules = screen.getByTestId("stop-money-rule");
    expect(rules.tagName).toBe("OL");
    expect(rules).toHaveTextContent("Captured when the boat arrives at this stop");
    expect(rules).toHaveTextContent("Voided if the stop is cancelled");
    expect(rules).not.toHaveTextContent("charged immediately");
  });

  it("says it in French", async () => {
    await i18n.changeLanguage("fr");
    await show({ pledge: pledge("stop_gift", "25") });
    expect(screen.getByTestId("stop-gift-note")).toHaveTextContent(/rien n’est débité aujourd’hui/);
    expect(screen.getByTestId("stop-gift-note")).toHaveTextContent(/1\s000\s€/);
    expect(within(screen.getByTestId("pledge-kind")).getByRole("option", { name: "Don à cette escale (retenu jusqu’à l’arrivée)" })).toBeInTheDocument();
  });

  it.each(["1000.01", "0", "-5", "12.345", "abc"])("offers no checkout for %s, and says why", async (amount) => {
    await show({ pledge: pledge("stop_gift", amount) });
    expect(screen.getByTestId("stop-gift-invalid")).toHaveTextContent("Enter an amount between €0.01 and €1,000");
    expect(screen.queryByTestId("pledge-values")).toBeNull();
    expect(screen.getByTestId("pledge-amount")).toHaveAttribute("aria-invalid", "true");
  });

  it("accepts the maximum exactly", async () => {
    await show({ pledge: pledge("stop_gift", "1000.00") });
    expect(screen.queryByTestId("stop-gift-invalid")).toBeNull();
    expect(buttonProps.at(-1).values.amount_eur).toBe("1000.00");
  });

  it("is closed on a cancelled stop, like every other pledge", async () => {
    vi.mocked(listMilestones).mockResolvedValue([{ id: STOP_ID, evidence: [], meta: { cancelled: true } }]);
    await show({ pledge: pledge("stop_gift", "25") });
    expect(screen.getByTestId("stop-cancelled-note")).toBeInTheDocument();
    expect(screen.queryByTestId("pledge-values")).toBeNull();
  });
});

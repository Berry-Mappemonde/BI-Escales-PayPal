import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fetchClock, fetchFund, listMilestones } from "../api/escales";
import i18n from "../i18n";
import en from "../i18n/locales/en.json";
import fr from "../i18n/locales/fr.json";
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
const pledge = (kind = "mile") => ({
  amount: "20",
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

describe("stop panel", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
    buttonProps.length = 0;
    vi.mocked(fetchClock).mockReset().mockResolvedValue({ now: "2026-11-20T08:00:00+00:00" });
    vi.mocked(listMilestones).mockReset().mockResolvedValue([{ id: STOP_ID, evidence: [] }]);
    vi.mocked(fetchFund).mockReset().mockResolvedValue({ authorized_eur: "120.50", captured_eur: "0.00" });
  });

  afterEach(cleanup);

  describe("status from the clock", () => {
    const chip = () => document.querySelector(".stop-chip");

    it.each([
      ["2026-11-05T08:00:00+00:00", "upcoming", "Upcoming"],
      ["2026-11-20T08:00:00+00:00", "en_route", "Underway"],
      ["2026-12-05T08:00:00+00:00", "arrived", "Arrived"],
    ])("at %s reads %s", async (now, status, label) => {
      vi.mocked(fetchClock).mockResolvedValue({ now });
      await show();
      expect(chip()).toHaveAttribute("data-status", status);
      expect(chip()).toHaveTextContent(label);
    });

    it("uses the teal route colour for En route and never amber", async () => {
      await show();
      expect(chip().style.getPropertyValue("--st")).toBe("var(--color-st-route)");
    });

    it("reads cancelled from the milestone, whatever the clock says", async () => {
      vi.mocked(listMilestones).mockResolvedValue([{ id: STOP_ID, evidence: [{ facts: { cancelled: true } }] }]);
      await show();
      expect(chip()).toHaveAttribute("data-status", "cancelled");
    });

    it.each([
      ["clock", () => vi.mocked(fetchClock).mockRejectedValue(new Error("down"))],
      ["milestones", () => vi.mocked(listMilestones).mockRejectedValue(new Error("down"))],
    ])("omits the chip when the %s call fails", async (_name, fail) => {
      fail();
      await show();
      expect(chip()).toBeNull();
    });

    it("omits the chip when the stop is not on the schedule", async () => {
      await show({ arrivalIso: "" });
      expect(chip()).toBeNull();
    });

    it("always labels the date as scheduled", async () => {
      vi.mocked(fetchClock).mockResolvedValue({ now: "2026-12-05T08:00:00+00:00" });
      await show();
      expect(screen.getByTestId("escale-estimated-arrival")).toHaveTextContent("Scheduled arrival");
      expect(screen.getByTestId("stop-scheduled-departure")).toHaveTextContent("Scheduled departure");
    });
  });

  describe("money line", () => {
    it("shows the held total", async () => {
      await show();
      expect(screen.getByTestId("stop-money")).toHaveTextContent("€120.50 pledged for this stop · not charged yet");
    });

    it("adds captured when it is not zero", async () => {
      vi.mocked(fetchFund).mockResolvedValue({ authorized_eur: "120.50", captured_eur: "30.00" });
      await show();
      expect(screen.getByTestId("stop-money")).toHaveTextContent("€120.50 pledged for this stop · not charged yet · €30 captured");
    });

    it("shows captured alone when nothing is held", async () => {
      vi.mocked(fetchFund).mockResolvedValue({ authorized_eur: "0.00", captured_eur: "30.00" });
      await show();
      expect(screen.getByTestId("stop-money").textContent).toBe("€30 captured");
    });

    it.each([
      ["zero", { authorized_eur: "0.00", captured_eur: "0.00" }],
      ["missing", {}],
      ["redacted", { authorized_eur: null, captured_eur: "" }],
    ])("is omitted when the fields are %s", async (_name, fund) => {
      vi.mocked(fetchFund).mockResolvedValue(fund);
      await show();
      expect(screen.queryByTestId("stop-money")).toBeNull();
    });

    it("is omitted when the fund call fails, and the panel still works", async () => {
      vi.mocked(fetchFund).mockRejectedValue(new Error("down"));
      await show();
      expect(screen.queryByTestId("stop-money")).toBeNull();
      expect(document.querySelector(".stop-chip")).not.toBeNull();
    });

    it("asks for the public fund, with no admin key", async () => {
      await show();
      expect(fetchFund).toHaveBeenCalledWith(STOP_ID);
    });

    it("never shows the previous stop's total after a switch", async () => {
      await show();
      let finish;
      vi.mocked(fetchFund).mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
      cleanup();
      render(tree({ stop: { ...stop, milestoneId: "dep-other", name: "Other" } }));
      expect(screen.queryByTestId("stop-money")).toBeNull();
      await act(async () => finish({ authorized_eur: "5.00" }));
      expect(screen.getByTestId("stop-money")).toHaveTextContent("€5 pledged");
    });
  });

  describe("no invented dates", () => {
    const DATE = /\d{1,2} [A-Za-zéû.]+ \d{4}/g;

    it.each([
      ["en", "2026-12-05T08:00:00+00:00", ["28 Nov 2026", "1 Dec 2026"]],
      ["fr", "2026-12-05T08:00:00+00:00", ["28 nov. 2026", "1 déc. 2026"]],
    ])("every date in %s traces back to an API field", async (lang, now, allowed) => {
      await i18n.changeLanguage(lang);
      vi.mocked(fetchClock).mockResolvedValue({ now });
      await show();
      const shown = document.querySelector(".escale-sheet").textContent.match(DATE) ?? [];
      const fromLogbook = lang === "en" ? "26 Nov 2026" : "26 nov. 2026";
      expect(shown.length).toBeGreaterThan(0);
      for (const date of shown) expect([...allowed, fromLogbook]).toContain(date);
    });

    it("shows no date at all when the schedule gives none", async () => {
      await show({ arrivalIso: "", schedule: {}, logbookEntries: [] });
      const text = document.querySelector(".escale-sheet").textContent;
      expect(text.match(DATE)).toBeNull();
      expect(screen.queryByTestId("escale-estimated-arrival")).toBeNull();
      expect(screen.queryByTestId("stop-scheduled-departure")).toBeNull();
    });

    it("leaves out a departure the schedule does not give", async () => {
      await show({ schedule: { ...schedule, legs: [schedule.legs[0]] } });
      expect(screen.queryByTestId("stop-scheduled-departure")).toBeNull();
    });

    it("shows dates without a clock time", async () => {
      vi.mocked(fetchClock).mockResolvedValue({ now: "2026-12-05T08:00:00+00:00" });
      await show();
      expect(document.querySelector(".escale-sheet").textContent).not.toMatch(/\d{2}:\d{2}|UTC/);
    });

    it("hard-codes no date in the new strings", () => {
      for (const block of [en.stopPanel, fr.stopPanel]) {
        expect(JSON.stringify(block)).not.toMatch(/20\d\d|\d{1,2} (Nov|Dec|nov|déc)/);
      }
    });
  });

  describe("logbook", () => {
    const logbookSection = () => screen.getByTestId("escale-logbook");

    it("is closed by default, like the port info", async () => {
      await show({ fiche: { sections: { mooring: { marinas: [{ name: "Tino Rossi", lat: 41.9, lon: 8.7 }] } } } });
      expect(logbookSection()).not.toHaveAttribute("open");
      expect(screen.getByTestId("stop-port-info")).not.toHaveAttribute("open");
      expect(screen.getByText("Tino Rossi")).toBeInTheDocument();
    });

    it("hides what the clock has not reached, and keeps the note with the rest", async () => {
      vi.mocked(fetchClock).mockResolvedValue({ now: "2026-11-27T08:00:00+00:00" });
      await show();
      expect(logbookSection()).toHaveTextContent("Position — underway for Ajaccio");
      expect(logbookSection()).not.toHaveTextContent("arrival at Ajaccio");
      expect(logbookSection()).toHaveTextContent("Computed from the schedule, not the boat's live position.");
    });

    it("says no entries yet before departure", async () => {
      vi.mocked(fetchClock).mockResolvedValue({ now: "2026-11-05T08:00:00+00:00" });
      await show();
      expect(logbookSection()).toHaveTextContent("No entries yet.");
      expect(logbookSection()).not.toHaveTextContent("Computed from the schedule");
    });

    it("is left out when the clock is unavailable, rather than saying no entries", async () => {
      vi.mocked(fetchClock).mockRejectedValue(new Error("down"));
      await show();
      expect(screen.queryByTestId("escale-logbook")).toBeNull();
    });
  });

  describe("next step", () => {
    it("wraps the existing form, with the agreed wording under it", async () => {
      await show();
      const block = within(screen.getByTestId("stop-next-step"));
      expect(block.getByRole("heading", { name: "Back this stop" })).toBeInTheDocument();
      expect(block.getByTestId("pledge-kind")).toBeInTheDocument();
      expect(block.getByTestId("pledge-amount")).toBeInTheDocument();
      expect(block.getByTestId("pledge-values")).toBeInTheDocument();
      expect(block.getByTestId("stop-money-rule").textContent).toBe(
        "Authorised now. Nothing is charged yet. Captured when the boat arrives at this stop, after the treasurer approves. Voided if the stop is cancelled. You pay nothing.",
      );
    });

    it("says the common fund is charged at once, never held", async () => {
      await show({ pledge: pledge("common_fund") });
      const rule = screen.getByTestId("stop-money-rule").textContent;
      expect(rule).toBe("The common fund is charged immediately, as soon as you approve in PayPal. It does not wait for the boat.");
      expect(rule).not.toMatch(/held|arrival/i);
    });

    it("says a cabin is captured at leg departure and voided with its leg", async () => {
      await show({ pledge: pledge("cabin_leg") });
      expect(screen.getByTestId("stop-money-rule").textContent).toBe(
        "Authorised now. Nothing is charged yet. Captured when this leg departs, after the treasurer approves. Voided if the leg is cancelled. You pay nothing.",
      );
    });

    it("labels the common fund as charged immediately in the Kind list, in both languages", async () => {
      await show();
      const option = () => within(screen.getByTestId("pledge-kind")).getByRole("option", { name: /common fund|caisse commune/i });
      expect(option()).toHaveTextContent("Common fund (charged immediately)");
      await act(async () => { await i18n.changeLanguage("fr"); });
      expect(option()).toHaveTextContent("Caisse commune (débitée immédiatement)");
    });

    it("sends the same values as before", async () => {
      await show();
      expect(JSON.parse(screen.getByTestId("pledge-values").textContent)).toMatchObject({
        milestone_id: STOP_ID,
        kind: "mile",
        target_id: STOP_ID,
      });
    });

    it("keeps the PayPal callback stable, so the buttons do not re-render", async () => {
      const onPledgeAuthorized = vi.fn();
      render(tree({ onPledgeAuthorized }));
      await waitFor(() => expect(document.querySelector(".stop-chip")).not.toBeNull());
      expect(buttonProps.length).toBeGreaterThan(1);
      expect(new Set(buttonProps.map((props) => props.onAuthorized)).size).toBe(1);
    });

    it("refreshes the held line after a pledge is authorized", async () => {
      const onPledgeAuthorized = vi.fn();
      await show({ onPledgeAuthorized });
      vi.mocked(fetchFund).mockResolvedValue({ authorized_eur: "140.50" });
      const done = { id: "p-1" };
      await act(async () => buttonProps.at(-1).onAuthorized(done));
      expect(onPledgeAuthorized).toHaveBeenCalledWith(done);
      expect(screen.getByTestId("stop-money")).toHaveTextContent("€140.50 pledged");
    });

    it("hides the form on a cancelled stop and explains why", async () => {
      vi.mocked(listMilestones).mockResolvedValue([{ id: STOP_ID, evidence: [], meta: { cancelled: true } }]);
      await show();
      expect(screen.queryByTestId("stop-next-step")).toBeNull();
      expect(screen.queryByTestId("pledge-kind")).toBeNull();
      expect(screen.getByTestId("stop-cancelled-note").textContent).toBe(
        "This stop is cancelled. New pledges are closed and existing authorisations are voided: nobody is charged.",
      );
    });

    it("keeps the form when the milestones call fails: the server still decides", async () => {
      vi.mocked(listMilestones).mockRejectedValue(new Error("down"));
      await show();
      expect(screen.getByTestId("stop-next-step")).toBeInTheDocument();
    });
  });

  it("keeps the FR and EN blocks in step", () => {
    const keys = (value, prefix = "") =>
      Object.entries(value).flatMap(([key, child]) =>
        typeof child === "object" ? keys(child, `${prefix}${key}.`) : [`${prefix}${key}`],
      );
    expect(keys(fr.stopPanel)).toEqual(keys(en.stopPanel));
  });
});

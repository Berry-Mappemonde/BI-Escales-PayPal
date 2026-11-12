/**
 * A3: the stop sheet shows what can be sponsored at this stop and at which fixed price,
 * and says how much is already pledged, including when that is nothing.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fetchClock, fetchFund, listMilestones } from "../api/escales";
import i18n from "../i18n";
import { unitPriceForKind } from "../pledge/stopPledgeAmount.js";
import { EscaleSheet } from "./EscaleSheet.jsx";

vi.mock("../api/escales", () => ({
  fetchClock: vi.fn(),
  fetchFund: vi.fn(),
  listMilestones: vi.fn(),
}));
vi.mock("./PledgeButton", () => ({ PledgeButton: () => <div data-testid="pledge-button" /> }));

const STOP_ID = "dep-la-rochelle";
const stop = { name: "La Rochelle", lat: 46.16, lon: -1.15, milestoneId: STOP_ID };
const schedule = { export: { escales: [{ milestone_id: STOP_ID, name: "La Rochelle", arrival_iso: "2026-11-12T12:00:00Z" }] }, legs: [] };
const catalog = {
  prices: [
    { kind: "mile", amount_eur: "1.00", free_amount: false },
    { kind: "project_pledge", free_amount: true },
    { kind: "berth", amount_eur: "30.00", free_amount: false },
    { kind: "night", amount_eur: "60.00", free_amount: false },
    { kind: "meal", amount_eur: "60.00", free_amount: false },
    { kind: "care", amount_eur: "40.00", free_amount: false },
    { kind: "cabin_leg", amount_eur: "80.00", free_amount: false },
    { kind: "stop_gift", free_amount: true },
    { kind: "common_fund", free_amount: true },
  ],
};
const pledge = { amount: "1", milestoneId: STOP_ID, contributor: "", kind: "mile", onAmount() {}, onMilestoneId() {}, onContributor() {}, onKind() {} };

async function show(props = {}) {
  render(
    <I18nextProvider i18n={i18n}>
      <EscaleSheet stop={stop} fiche={null} schedule={schedule} arrivalIso="2026-11-12T12:00:00Z" logbookEntries={[]} pledge={pledge} priceCatalog={catalog} {...props} />
    </I18nextProvider>,
  );
  await waitFor(() => expect(fetchFund).toHaveBeenCalled());
  await screen.findByTestId("escale-estimated-arrival");
}

const optionNames = () => within(screen.getByTestId("pledge-kind")).getAllByRole("option").map((option) => option.textContent);

describe("stop sheet: fixed prices and what is already pledged", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
    vi.mocked(fetchClock).mockResolvedValue({ now: "2026-11-12T08:00:00+00:00" });
    vi.mocked(listMilestones).mockResolvedValue([]);
    vi.mocked(fetchFund).mockResolvedValue({ authorized_eur: "0.00", captured_eur: "0.00" });
  });
  afterEach(() => vi.clearAllMocks());

  it("names the fixed price in every option, and none for a free amount", async () => {
    await show();
    expect(optionNames()).toEqual([
      "Sponsored miles (simulation) — €1",
      "Berth reservation (simulation) — €30",
      "Night aboard (simulation) — €60",
      "Meal (simulation) — €60",
      "Wellness programme (simulation) — €40",
      "Cabin on a leg (simulation) — €80",
      "Gift to this stop (held until arrival)",
      "Common fund (charged immediately)",
    ]);
  });

  it("lists every fixed price on one line, without opening the list", async () => {
    await show();
    expect(screen.getByTestId("stop-fixed-prices").textContent).toBe(
      "Fixed prices: mile €1 · berth €30 · night €60 · meal €60 · wellness €40 · cabin €80",
    );
  });

  it("follows the catalogue, not a hard-coded list", async () => {
    await show({ priceCatalog: { prices: [{ kind: "berth", amount_eur: "35.50" }, { kind: "night", amount_eur: "70.00" }] } });
    expect(screen.getByTestId("stop-fixed-prices")).toHaveTextContent("berth €35.50 · night €70");
    expect(optionNames()).toContain("Berth reservation (simulation) — €35.50");
  });

  it("still shows the known prices before the catalogue has loaded", async () => {
    await show({ priceCatalog: undefined });
    expect(screen.getByTestId("stop-fixed-prices").textContent).toBe(
      "Fixed prices: mile €1 · berth €30 · night €60 · meal €60 · wellness €40 · cabin €80",
    );
  });

  it("keeps the option values the checkout reads", async () => {
    await show();
    expect(within(screen.getByTestId("pledge-kind")).getAllByRole("option").map((option) => option.value)).toEqual([
      "mile", "berth", "night", "meal", "care", "cabin_leg", "stop_gift", "common_fund",
    ]);
  });

  it("is written in French too", async () => {
    await i18n.changeLanguage("fr");
    await show();
    // French puts a no-break space before the euro sign; compare with plain spaces.
    expect(screen.getByTestId("stop-fixed-prices").textContent.replace(/\s/g, " ")).toBe(
      "Tarifs fixes : mille 1 € · place de port 30 € · nuit 60 € · repas 60 € · bien-être 40 € · cabine 80 €",
    );
    expect(optionNames()[1].replace(/\s/g, " ")).toMatch(/ — 30 €$/);
    expect(screen.getByTestId("stop-money-none")).toHaveTextContent("Aucune promesse pour cette escale pour l’instant");
  });

  it("says so when nothing is pledged yet", async () => {
    await show();
    expect(screen.getByTestId("stop-money-none")).toHaveTextContent("Nothing pledged for this stop yet");
    expect(screen.queryByTestId("stop-money")).toBeNull();
  });

  it("shows the amounts instead once there is a pledge", async () => {
    vi.mocked(fetchFund).mockResolvedValue({ authorized_eur: "1.00", captured_eur: "0.00" });
    await show();
    expect(screen.getByTestId("stop-money")).toHaveTextContent("€1 pledged for this stop · not charged yet");
    expect(screen.queryByTestId("stop-money-none")).toBeNull();
  });

  it.each([
    ["the call failed", null],
    ["the fields are missing", {}],
    ["the fields are redacted", { authorized_eur: null, captured_eur: "" }],
  ])("says nothing about the total when %s", async (_case, fund) => {
    if (fund === null) vi.mocked(fetchFund).mockRejectedValue(new Error("down"));
    else vi.mocked(fetchFund).mockResolvedValue(fund);
    await show();
    expect(screen.queryByTestId("stop-money-none")).toBeNull();
    expect(screen.queryByTestId("stop-money")).toBeNull();
  });
});

describe("unitPriceForKind", () => {
  it("returns the catalogue price, 1.00 for a mile, and null for a free amount", () => {
    expect(unitPriceForKind("berth", catalog)).toBe("30.00");
    expect(unitPriceForKind("mile", catalog)).toBe("1.00");
    expect(unitPriceForKind("mile", undefined)).toBe("1.00");
    expect(unitPriceForKind("care", undefined)).toBe("40.00");
    expect(unitPriceForKind("common_fund", catalog)).toBeNull();
    expect(unitPriceForKind("common_fund", undefined)).toBeNull();
    expect(unitPriceForKind("", catalog)).toBeNull();
  });
});

/** B9: the treasurer follows the Crew memberships: who is subscribed, and each status. Read-only. */
import { render, screen, waitFor, within } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import * as api from "../api/escales";
import { TreasurerCrewMemberships, crewMembershipRows } from "./TreasurerCrewMemberships";
import { TreasurerPayPalPanel } from "./TreasurerPayPalPanel";
import { formatPledgeCreatedAt } from "./TreasurerQueue";

/** The date as the table writes it, in whatever time zone the tests run. */
const when = (iso: string) => formatPledgeCreatedAt(iso, "en");

vi.mock("../api/escales", async (load) => ({
  ...(await load<typeof import("../api/escales")>()),
  fetchPayPalDisputes: vi.fn(),
  fetchPayPalInvoices: vi.fn(),
  fetchPayPalSubscriptions: vi.fn(),
  fetchCrewSupporterPlan: vi.fn(),
  setupCrewSubscription: vi.fn(),
  approveCrewSubscription: vi.fn(),
  recordSubscription: vi.fn(),
}));

const items = [
  { subscription_id: "I-OLDEST00001", plan_id: "P-1", status: "CANCELLED", subscriber_email: "old@example.com", at: "2026-11-01T09:00:00Z", updated_at: "2026-11-05T10:30:00Z" },
  { subscription_id: "I-NEWEST00003", plan_id: "P-1", status: "ACTIVE", subscriber_email: "new@example.com", at: "2026-11-10T12:00:00Z", updated_at: "2026-11-10T12:00:00Z" },
  { subscription_id: "I-MIDDLE00002", plan_id: "P-1", status: "APPROVAL_PENDING", subscriber_email: null, at: "2026-11-07T08:00:00Z" },
];

const show = (rows: unknown) =>
  render(
    <I18nextProvider i18n={i18n}>
      <TreasurerCrewMemberships items={rows} />
    </I18nextProvider>,
  );
const cells = (id: string) => [...screen.getByTestId(`crew-row-${id}`).querySelectorAll("td")].map((cell) => cell.textContent);

describe("TreasurerCrewMemberships", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
  });
  afterEach(() => vi.clearAllMocks());

  it("lists who is subscribed with each status, newest first", () => {
    show(items);
    expect(screen.getByRole("heading", { name: "Crew memberships" })).toBeInTheDocument();
    expect(screen.getAllByRole("row").slice(1).map((row) => row.getAttribute("data-testid"))).toEqual([
      "crew-row-I-NEWEST00003",
      "crew-row-I-MIDDLE00002",
      "crew-row-I-OLDEST00001",
    ]);
    expect(cells("I-NEWEST00003")).toEqual(["new@example.com", "Active", when("2026-11-10T12:00:00Z"), when("2026-11-10T12:00:00Z"), "I-NEWEST"]);
    expect(cells("I-OLDEST00001")).toEqual(["old@example.com", "Cancelled", when("2026-11-01T09:00:00Z"), when("2026-11-05T10:30:00Z"), "I-OLDEST"]);
    expect(screen.getAllByRole("columnheader").map((cell) => cell.textContent)).toEqual([
      "Member", "Status", "Since", "Last change", "Subscription",
    ]);
  });

  it("says when PayPal shared no email, and uses the start date when there was no change", () => {
    show(items);
    expect(cells("I-MIDDLE00002")).toEqual(["Email not shared by PayPal", "Waiting for approval", when("2026-11-07T08:00:00Z"), when("2026-11-07T08:00:00Z"), "I-MIDDLE"]);
  });

  it("counts the memberships and the active ones", () => {
    show(items);
    expect(screen.getByTestId("treasurer-crew-summary")).toHaveTextContent("3 memberships · 1 active");
  });

  it("uses the singular for one membership", () => {
    show([items[1]]);
    expect(screen.getByTestId("treasurer-crew-summary")).toHaveTextContent("1 membership · 1 active");
  });

  it("agrees in French: two active memberships are \"actives\"", async () => {
    await i18n.changeLanguage("fr");
    show([items[1], { ...items[1], subscription_id: "I-SECOND" }]);
    expect(screen.getByTestId("treasurer-crew-summary")).toHaveTextContent("2 adhésions · 2 actives");
  });

  it("keeps the full subscription id one hover away", () => {
    show(items);
    expect(within(screen.getByTestId("crew-row-I-NEWEST00003")).getByText("I-NEWEST")).toHaveAttribute("title", "I-NEWEST00003");
  });

  it("shows a status PayPal may add later as it was sent, and a missing one as a dash", () => {
    show([{ subscription_id: "I-A", status: "paused" }, { subscription_id: "I-B" }]);
    expect(cells("I-A")[1]).toBe("PAUSED");
    expect(cells("I-B")[1]).toBe("—");
    expect(cells("I-B")[2]).toBe("—");
  });

  it("says so when nobody has subscribed yet", () => {
    show([]);
    expect(screen.getByTestId("treasurer-crew-empty")).toHaveTextContent("No Crew membership yet.");
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("is read-only: no button, no link, no field", () => {
    show(items);
    const section = screen.getByTestId("treasurer-crew-memberships");
    expect(section.querySelectorAll("button, a, input, select, textarea")).toHaveLength(0);
    expect(section).toHaveTextContent("Read-only. A membership starts and ends in PayPal.");
  });

  it("ignores rows that are not subscriptions", () => {
    expect(crewMembershipRows([null, "x", {}, { subscription_id: " " }, { subscription_id: "I-OK" }])).toEqual([{ subscription_id: "I-OK" }]);
    expect(crewMembershipRows(undefined)).toEqual([]);
    expect(crewMembershipRows({ items: [] })).toEqual([]);
  });

  it("is written in French too", async () => {
    await i18n.changeLanguage("fr");
    show(items);
    expect(screen.getByRole("heading", { name: "Adhésions Crew" })).toBeInTheDocument();
    expect(screen.getByTestId("treasurer-crew-summary")).toHaveTextContent("3 adhésions · 1 active");
    expect(cells("I-OLDEST00001")[1]).toBe("Résiliée");
    expect(cells("I-MIDDLE00002").slice(0, 2)).toEqual(["E-mail non communiqué par PayPal", "En attente d’approbation"]);
  });
});

describe("TreasurerPayPalPanel: Crew memberships", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
    vi.mocked(api.fetchPayPalDisputes).mockResolvedValue({ paypal: { items: [] } } as never);
    vi.mocked(api.fetchPayPalInvoices).mockResolvedValue({ paypal: { items: [] } } as never);
    vi.mocked(api.fetchPayPalSubscriptions).mockResolvedValue({ items });
    vi.mocked(api.fetchCrewSupporterPlan).mockResolvedValue({ plan_id: "P-1" });
  });
  afterEach(() => vi.clearAllMocks());

  const panel = (adminKey: string) =>
    render(
      <I18nextProvider i18n={i18n}>
        <TreasurerPayPalPanel adminKey={adminKey} />
      </I18nextProvider>,
    );

  it("lists the memberships from the same read as the count, with the treasurer key", async () => {
    panel("treasurer-key");
    await screen.findByTestId("crew-row-I-NEWEST00003");
    expect(screen.getByTestId("treasurer-subscription-count")).toHaveTextContent("Crew memberships: 3");
    expect(api.fetchPayPalSubscriptions).toHaveBeenCalledTimes(1);
    expect(api.fetchPayPalSubscriptions).toHaveBeenCalledWith("treasurer-key");
  });

  it("changes nothing in PayPal: it only reads", async () => {
    panel("treasurer-key");
    await screen.findByTestId("crew-row-I-NEWEST00003");
    expect(api.setupCrewSubscription).not.toHaveBeenCalled();
    expect(api.approveCrewSubscription).not.toHaveBeenCalled();
    expect(api.recordSubscription).not.toHaveBeenCalled();
  });

  it("shows nothing without the key", () => {
    const view = panel("  ");
    expect(view.container).toBeEmptyDOMElement();
    expect(api.fetchPayPalSubscriptions).not.toHaveBeenCalled();
  });

  it("shows no list when the read fails", async () => {
    vi.mocked(api.fetchPayPalSubscriptions).mockRejectedValue(new Error("Admin key rejected"));
    panel("wrong-key");
    await waitFor(() => expect(screen.getByText("Admin key rejected")).toBeInTheDocument());
    expect(screen.queryByTestId("treasurer-crew-memberships")).toBeNull();
  });
});

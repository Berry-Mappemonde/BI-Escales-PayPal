/** Brief item B2: every status a pledge can have is visible in the queue, and explained in words. */
import { render, screen, within } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { captainReview } from "../api/escales";
import type { PublicPledge } from "../api/types";
import i18n from "../i18n";
import { TreasurerQueue } from "./TreasurerQueue";

vi.mock("../api/escales", () => ({
  approveCaptainReview: vi.fn(),
  captainReview: vi.fn(),
  capturePledge: vi.fn(),
  fetchSchedule: vi.fn().mockResolvedValue({}),
  refundPledge: vi.fn(),
  voidPledge: vi.fn(),
}));

const row = (id: string, status: string, day: number, over: Partial<PublicPledge> = {}): PublicPledge =>
  ({
    id,
    status,
    intent: "AUTHORIZE",
    currency: "EUR",
    amount_eur: "20.00",
    description: "20 sponsored miles",
    milestone_id: "dep-la-rochelle",
    created_at: `2026-11-${String(day).padStart(2, "0")}T09:00:00Z`,
    ...over,
  }) as PublicPledge;

const everyStatus = [
  row("p-held", "authorized", 1),
  row("p-saved", "vaulted", 2),
  row("p-captured", "captured", 3, { capture_id: "CAP-1" }),
  row("p-released", "voided", 4),
  row("p-refunded", "refunded", 5, { capture_id: "CAP-2" }),
];

function show(pledges: PublicPledge[], props: { needsKey?: boolean; adminKey?: string } = {}) {
  vi.mocked(captainReview).mockResolvedValue({ milestone_id: "dep-la-rochelle", proposal: "wait", pledge_ids: [] });
  render(
    <I18nextProvider i18n={i18n}>
      <TreasurerQueue
        pledges={pledges}
        adminKey={props.adminKey ?? "key"}
        needsKey={props.needsKey}
        stopNames={{ "dep-la-rochelle": "La Rochelle" }}
        onRefresh={() => {}}
        onUpdated={() => {}}
      />
    </I18nextProvider>,
  );
}

describe("pledge statuses in the treasurer queue", () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    await i18n.changeLanguage("en");
  });

  it("explains the five statuses in plain words", () => {
    show(everyStatus);
    const legend = screen.getByRole("list", { name: "What each status means" });
    const lines = within(legend).getAllByRole("listitem").map((item) => item.textContent);
    expect(lines).toEqual([
      "Heldauthorised by PayPal, not charged yet",
      "Savedwaiting: payment method saved with PayPal for a stop more than 29 days away, charged on arrival",
      "Capturedcharged",
      "Releasedauthorisation voided, nothing was charged",
      "Refundedmoney returned after a capture",
    ]);
  });

  it("explains them in French too", async () => {
    await i18n.changeLanguage("fr");
    show(everyStatus);
    const legend = screen.getByRole("list", { name: "Ce que signifie chaque statut" });
    expect(legend).toHaveTextContent("autorisée par PayPal, pas encore débitée");
    expect(legend).toHaveTextContent("argent rendu après un encaissement");
  });

  it("keeps open pledges in the queue and lists released and refunded ones under it, read-only", () => {
    show(everyStatus);
    for (const id of ["p-held", "p-saved", "p-captured"]) {
      expect(screen.getByTestId(`queue-row-${id}`)).toBeInTheDocument();
    }
    expect(screen.queryByTestId("queue-row-p-released")).toBeNull();
    expect(screen.queryByTestId("queue-row-p-refunded")).toBeNull();

    const closed = screen.getByTestId("queue-closed");
    expect(within(closed).getByRole("heading", { name: "Closed pledges" })).toBeInTheDocument();
    // Newest first.
    const rows = within(closed).getAllByRole("row").slice(1);
    expect(rows.map((r) => r.getAttribute("data-testid"))).toEqual(["closed-row-p-refunded", "closed-row-p-released"]);
    expect(within(rows[0]).getByText("Refunded")).toBeInTheDocument();
    expect(within(rows[1]).getByText("Released")).toBeInTheDocument();
    expect(within(rows[0]).getByText("La Rochelle")).toBeInTheDocument();
    // Nothing to decide there: no button at all.
    expect(within(closed).queryByRole("button")).toBeNull();
  });

  it("lists the eight newest closed pledges and counts the older ones", () => {
    const many = Array.from({ length: 11 }, (_unused, index) => row(`p-${index}`, "voided", index + 1));
    show(many);
    const closed = screen.getByTestId("queue-closed");
    expect(within(closed).getAllByRole("row").slice(1)).toHaveLength(8);
    expect(screen.getByTestId("queue-closed-more")).toHaveTextContent("And 3 older closed pledges.");
  });

  it("shows no closed list when nothing is closed, and neither list nor legend without access", () => {
    show([row("p-held", "authorized", 1)]);
    expect(screen.queryByTestId("queue-closed")).toBeNull();
    expect(screen.getByTestId("queue-status-legend")).toBeInTheDocument();
  });

  it("says in plain words that nothing is waiting", () => {
    show([row("p-released", "voided", 4)]);
    expect(screen.getByText("No pledge is waiting for a decision right now.")).toBeInTheDocument();
    expect(screen.getByTestId("closed-row-p-released")).toBeInTheDocument();
  });

  it("shows nothing about pledges to a visitor who has no key and no demo", () => {
    show(everyStatus, { needsKey: true, adminKey: "" });
    expect(screen.queryByTestId("queue-status-legend")).toBeNull();
    expect(screen.queryByTestId("queue-closed")).toBeNull();
  });
});

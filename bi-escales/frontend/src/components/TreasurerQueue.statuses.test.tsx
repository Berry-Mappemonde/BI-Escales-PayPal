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
  row("p-pending", "pending", 6),
  row("p-partly", "partially_refunded", 7, { capture_id: "CAP-3" }),
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

  it("explains every status the queue can show, in plain words", () => {
    show(everyStatus);
    const legend = screen.getByRole("list", { name: "What each status means" });
    const lines = within(legend).getAllByRole("listitem").map((item) => item.textContent);
    expect(lines).toEqual([
      "Heldauthorised by PayPal, not charged yet",
      "Savedwaiting: payment method saved with PayPal for a stop or cabin more than 29 days away; charged when the boat arrives (stops) or at leg departure (cabins)",
      "Pendingcapture asked, PayPal is still processing the payment",
      "Capturedcharged",
      "Releasedauthorisation voided, nothing was charged",
      "Partly refundedpart of a captured payment returned; the rest can still be refunded",
      "Refundedmoney returned after a capture",
    ]);
    // Every chip the queue shows is explained in the legend.
    const explained = within(legend).getAllByRole("listitem").map((item) => item.firstElementChild?.textContent);
    for (const id of ["p-held", "p-saved", "p-pending", "p-captured", "p-partly"]) {
      const chip = within(screen.getByTestId(`queue-row-${id}`)).getByText(/Held|Saved|Pending|Captured|Partly refunded/);
      expect(explained).toContain(chip.textContent);
    }
  });

  it("explains them in French too", async () => {
    await i18n.changeLanguage("fr");
    show(everyStatus);
    const legend = screen.getByRole("list", { name: "Ce que signifie chaque statut" });
    expect(legend).toHaveTextContent("autorisée par PayPal, pas encore débitée");
    expect(legend).toHaveTextContent("argent rendu après un encaissement");
    // A saved payment method is charged at leg departure for a cabin, not on arrival.
    expect(legend).toHaveTextContent("débité à l’arrivée du bateau (escales) ou au départ de l’étape (cabines)");
    expect(legend).toHaveTextContent("encaissement demandé, PayPal traite encore le paiement");
    expect(legend).toHaveTextContent("une partie de l’encaissement rendue ; le reste peut encore être remboursé");
  });

  it("keeps open pledges in the queue and lists released and refunded ones under it, read-only", () => {
    show(everyStatus);
    for (const id of ["p-held", "p-saved", "p-captured", "p-pending", "p-partly"]) {
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

  it("dates closed pledges by their release or refund when the list says, newest closure first", () => {
    show([
      // Created first but refunded last: it comes first.
      row("p-old-refunded", "refunded", 1, { capture_id: "CAP-9", refunded_at: "2026-11-12T08:30:00Z" }),
      row("p-new-released", "voided", 9, { voided_at: "2026-11-10T10:00:00Z" }),
      // A list without closure times (the demo list): its creation date, said as such.
      row("p-no-time", "voided", 5),
    ]);
    const closed = screen.getByTestId("queue-closed");
    expect(within(closed).getByRole("columnheader", { name: "Released or refunded" })).toBeInTheDocument();
    const rows = within(closed).getAllByRole("row").slice(1);
    expect(rows.map((r) => r.getAttribute("data-testid"))).toEqual([
      "closed-row-p-old-refunded",
      "closed-row-p-new-released",
      "closed-row-p-no-time",
    ]);
    expect(rows[0].querySelector("time")).toHaveAttribute("datetime", "2026-11-12T08:30:00Z");
    expect(rows[1].querySelector("time")).toHaveAttribute("datetime", "2026-11-10T10:00:00Z");
    expect(rows[2].querySelector("time")).toHaveTextContent(/^created /);
    expect(rows[2].querySelector("time")).toHaveAttribute("datetime", "2026-11-05T09:00:00Z");
  });

  it("shows no closed list when nothing is closed", () => {
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

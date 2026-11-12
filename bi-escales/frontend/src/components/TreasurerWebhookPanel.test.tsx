import { render, screen, waitFor, within } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import { fetchRecentWebhooks } from "../api/escales";
import { TreasurerWebhookPanel } from "./TreasurerWebhookPanel";

vi.mock("../api/escales", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/escales")>();
  return { ...mod, fetchRecentWebhooks: vi.fn() };
});

// Newest first, as the server sends them.
const events = [
  { transmission_id: "t3", event_type: "PAYMENT.CAPTURE.COMPLETED", outcome: "accepted", pledge_id: "31687a4e-aaaa-bbbb-cccc-000000000001", time: "2026-11-12T09:43:10Z" },
  { transmission_id: "t2", event_type: "PAYMENT.CAPTURE.COMPLETED", outcome: "duplicate", pledge_id: "31687a4e-aaaa-bbbb-cccc-000000000001", time: "2026-11-12T09:43:05Z" },
  { transmission_id: "t1", event_type: "PAYMENT.AUTHORIZATION.VOIDED", outcome: "rejected", pledge_id: null, time: "2026-11-05T00:00:00Z" },
];

function show(adminKey = "secret") {
  render(
    <I18nextProvider i18n={i18n}>
      <TreasurerWebhookPanel adminKey={adminKey} />
    </I18nextProvider>,
  );
}

describe("TreasurerWebhookPanel", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
    vi.mocked(fetchRecentWebhooks).mockReset().mockResolvedValue(events);
  });

  afterEach(async () => {
    await i18n.changeLanguage("en");
  });

  it("lists the notifications when the treasurer key is present", async () => {
    show();
    expect(await screen.findByTestId("treasurer-webhook-panel")).toBeInTheDocument();
    expect(await screen.findByText("PAYMENT.AUTHORIZATION.VOIDED")).toBeInTheDocument();
    expect(screen.getAllByTestId("webhook-row")).toHaveLength(3);
    // The button refreshes this list, and says so (it used to read "Refresh queue").
    expect(screen.getByRole("button", { name: "Refresh notifications" })).toBeInTheDocument();
  });

  it("says when the last notification came in, what it was, and how many were recorded", async () => {
    show();
    const status = await screen.findByTestId("paypal-notifications-status");
    expect(screen.getByRole("heading", { name: "PayPal notifications" })).toBeInTheDocument();
    expect(status).toHaveTextContent("Last received: 12 Nov 2026, 09:43 UTC");
    expect(status).toHaveTextContent("PAYMENT.CAPTURE.COMPLETED");
    expect(status).toHaveTextContent("Verified, ledger updated");
    expect(screen.getByTestId("paypal-notifications-count")).toHaveTextContent("3 notifications recorded in total.");
  });

  it("writes each outcome in words and each time as a date, with the pledge reference shortened", async () => {
    show();
    const rows = await screen.findAllByTestId("webhook-row");
    expect(within(rows[0]).getByText("Verified, ledger updated")).toBeInTheDocument();
    expect(within(rows[1]).getByText("Already recorded, ignored")).toBeInTheDocument();
    expect(within(rows[2]).getByText("Rejected, not applied")).toBeInTheDocument();
    expect(within(rows[2]).getByText("5 Nov 2026, 00:00 UTC")).toBeInTheDocument();
    expect(within(rows[0]).getByText("31687a4e")).toHaveAttribute("title", "31687a4e-aaaa-bbbb-cccc-000000000001");
    expect(rows[0].textContent).not.toContain("2026-11-12T09:43:10Z");
  });

  it("counts every notification but lists the latest twenty", async () => {
    const many = Array.from({ length: 23 }, (_unused, index) => ({
      transmission_id: `t${index}`,
      event_type: "PAYMENT.CAPTURE.COMPLETED",
      outcome: "accepted",
      pledge_id: null,
      time: `2026-11-12T09:${String(59 - index).padStart(2, "0")}:00Z`,
    }));
    vi.mocked(fetchRecentWebhooks).mockResolvedValue(many);
    show();
    expect(await screen.findAllByTestId("webhook-row")).toHaveLength(20);
    expect(screen.getByTestId("paypal-notifications-count")).toHaveTextContent("23 notifications recorded in total.");
    expect(screen.getByText("The latest 20 notifications")).toBeInTheDocument();
  });

  it("says so, without an empty table, when PayPal has sent nothing yet", async () => {
    vi.mocked(fetchRecentWebhooks).mockResolvedValue([]);
    show();
    expect(await screen.findByTestId("paypal-notifications-status")).toHaveTextContent(
      "No notification received from PayPal yet.",
    );
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("does not say \"none yet\" before the first answer", async () => {
    vi.mocked(fetchRecentWebhooks).mockReturnValue(new Promise(() => undefined));
    show();
    await screen.findByTestId("treasurer-webhook-panel");
    expect(screen.queryByTestId("paypal-notifications-status")).toBeNull();
  });

  it("speaks French", async () => {
    await i18n.changeLanguage("fr");
    show();
    const status = await screen.findByTestId("paypal-notifications-status");
    expect(screen.getByRole("heading", { name: "Notifications PayPal" })).toBeInTheDocument();
    expect(status).toHaveTextContent(/Dernière reçue\s: 12 nov\. 2026/);
    expect(status).toHaveTextContent("Vérifiée, registre mis à jour");
  });

  it("shows nothing and asks nothing without the treasurer key", async () => {
    show("  ");
    await waitFor(() => expect(screen.queryByTestId("treasurer-webhook-panel")).toBeNull());
    expect(fetchRecentWebhooks).not.toHaveBeenCalled();
  });
});

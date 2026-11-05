import { render, screen } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import { fetchRecentWebhooks } from "../api/escales";
import { TreasurerWebhookPanel } from "./TreasurerWebhookPanel";

vi.mock("../api/escales", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/escales")>();
  return { ...mod, fetchRecentWebhooks: vi.fn() };
});

describe("TreasurerWebhookPanel", () => {
  beforeEach(() => {
    vi.mocked(fetchRecentWebhooks).mockResolvedValue([
      {
        transmission_id: "t1",
        event_type: "PAYMENT.AUTHORIZATION.VOIDED",
        outcome: "accepted",
        pledge_id: "p1",
        time: "2026-11-05T00:00:00Z",
      },
    ]);
  });

  it("liste les webhooks quand la clé admin est présente", async () => {
    render(
      <I18nextProvider i18n={i18n}>
        <TreasurerWebhookPanel adminKey="secret" />
      </I18nextProvider>,
    );
    expect(await screen.findByTestId("treasurer-webhook-panel")).toBeInTheDocument();
    expect(await screen.findByText("PAYMENT.AUTHORIZATION.VOIDED")).toBeInTheDocument();
  });
});

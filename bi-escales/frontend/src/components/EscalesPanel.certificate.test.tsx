/** Brief item A6: a miles pledge made from the Captain's cart offers its certificate right there. */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as escalesApi from "../api/escales";
import type { CaptainChatResponse, PublicPledge } from "../api/types";
import i18n from "../i18n";
import { EscalesPanel } from "./EscalesPanel";

vi.mock("../api/escales", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/escales")>();
  return {
    ...actual,
    captainChat: vi.fn(),
    issueMileCertificate: vi.fn(),
  };
});

/** What the PayPal button hands back once the payer has approved. */
let authorized: PublicPledge;
const seenCallbacks: unknown[] = [];

vi.mock("./PledgeButton", () => ({
  PledgeButton: ({ onAuthorized }: { onAuthorized?: (pledge: PublicPledge) => void }) => {
    seenCallbacks.push(onAuthorized);
    return (
      <button type="button" data-testid="fake-paypal" onClick={() => onAuthorized?.(authorized)}>
        pay
      </button>
    );
  },
}));

const milePledge = (over: Partial<PublicPledge> = {}): PublicPledge =>
  ({
    id: "p-mile-1",
    kind: "mile",
    status: "authorized",
    intent: "AUTHORIZE",
    amount_eur: "20.00",
    currency: "EUR",
    description: "20 nautical miles",
    milestone_id: "dep-mayotte",
    order_id: "ORDER-1",
    contributor: "Ada",
    ...over,
  }) as PublicPledge;

const reply = {
  reply: "20 miles near Mayotte: 20 EUR.",
  cart: {
    currency: "EUR",
    lines: [
      {
        kind: "mile",
        description: "20 nautical miles",
        amount_eur: "20.00",
        quantity: 20,
        pledge: { amount_eur: "20.00", description: "20 nautical miles", milestone_id: "dep-mayotte", kind: "mile" },
      },
    ],
  },
} as unknown as CaptainChatResponse;

async function askAndPay(onAuthorized = vi.fn()) {
  render(
    <I18nextProvider i18n={i18n}>
      <EscalesPanel milestoneId="dep-mayotte" onAuthorized={onAuthorized} />
    </I18nextProvider>,
  );
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "Sponsor 20 miles near Mayotte" } });
  fireEvent.submit(screen.getByRole("textbox").closest("form")!);
  await screen.findByTestId("captain-cart");
  fireEvent.click(screen.getByTestId("fake-paypal"));
  return onAuthorized;
}

describe("mile certificate under the Captain's cart", () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    seenCallbacks.length = 0;
    await i18n.changeLanguage("en");
    vi.mocked(escalesApi.captainChat).mockResolvedValue(reply);
    vi.mocked(escalesApi.issueMileCertificate).mockResolvedValue({
      token: "opaque-token",
      png: "/api/escales/certificates/opaque-token.png",
      pdf: "/api/escales/certificates/opaque-token.pdf",
      mile_number: 41,
      mile_quantity: 20,
      issue_date: "2026-11-12",
    } as never);
  });

  it("offers the certificate after a miles pledge, and still tells the app about the pledge", async () => {
    authorized = milePledge();
    const onAuthorized = await askAndPay();

    const block = await screen.findByTestId("mile-certificate-receipt");
    expect(block).toHaveTextContent("Your mile certificate, with a note from the AI Captain");
    await waitFor(() => expect(screen.getByTestId("mile-certificate-png")).toHaveTextContent("Download PNG"));
    expect(screen.getByTestId("mile-certificate-pdf")).toHaveTextContent("Download PDF");
    expect(screen.getByTestId("captain-cart")).toContainElement(block);
    expect(escalesApi.issueMileCertificate).toHaveBeenCalledWith("p-mile-1", "ORDER-1", "Ada", "en");
    expect(onAuthorized).toHaveBeenCalledWith(authorized);
  });

  it("shows no certificate for a pledge that is not for miles", async () => {
    authorized = milePledge({ id: "p-berth", kind: "berth_night" });
    const onAuthorized = await askAndPay();
    expect(onAuthorized).toHaveBeenCalledWith(authorized);
    expect(screen.queryByTestId("mile-certificate-receipt")).toBeNull();
    expect(escalesApi.issueMileCertificate).not.toHaveBeenCalled();
  });

  it("hands the PayPal button one stable function, so the buttons are not redrawn", async () => {
    authorized = milePledge();
    await askAndPay();
    await screen.findByTestId("mile-certificate-receipt");
    expect(seenCallbacks.length).toBeGreaterThan(1);
    expect(new Set(seenCallbacks).size).toBe(1);
  });
});

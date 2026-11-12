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

  it("says before paying that a miles line comes with a certificate, then gives way to it", async () => {
    render(
      <I18nextProvider i18n={i18n}>
        <EscalesPanel milestoneId="dep-mayotte" />
      </I18nextProvider>,
    );
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "Sponsor 20 miles near Mayotte" } });
    fireEvent.submit(screen.getByRole("textbox").closest("form")!);
    const promise = await screen.findByTestId("captain-cart-certificate-promise");
    expect(promise).toHaveTextContent(/the nearest marine project/);
    authorized = milePledge();
    fireEvent.click(screen.getByTestId("fake-paypal"));
    await screen.findByTestId("mile-certificate-receipt");
    expect(screen.queryByTestId("captain-cart-certificate-promise")).toBeNull();
  });

  it("drops the previous certificate when the Captain answers with a new cart", async () => {
    authorized = milePledge();
    await askAndPay();
    await screen.findByTestId("mile-certificate-receipt");

    vi.mocked(escalesApi.captainChat).mockResolvedValue({
      reply: "One berth night in Ajaccio: 35 EUR.",
      cart: {
        currency: "EUR",
        lines: [
          {
            kind: "berth_night",
            description: "1 berth night",
            amount_eur: "35.00",
            quantity: 1,
            pledge: { amount_eur: "35.00", description: "1 berth night", milestone_id: "dep-ajaccio-corse", kind: "berth_night" },
          },
        ],
      },
    } as unknown as CaptainChatResponse);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "A berth night in Ajaccio" } });
    fireEvent.submit(screen.getByRole("textbox").closest("form")!);
    await waitFor(() => expect(screen.getByTestId("captain-cart")).toHaveTextContent("1 berth night"));
    expect(screen.queryByTestId("mile-certificate-receipt")).toBeNull();
    expect(screen.queryByTestId("captain-cart-certificate-promise")).toBeNull();
  });

  it("keeps one certificate per miles pledge when the cart has two miles lines", async () => {
    const line = reply.cart!.lines![0]!;
    vi.mocked(escalesApi.captainChat).mockResolvedValue({
      ...reply,
      cart: { currency: "EUR", lines: [line, { ...line, description: "5 nautical miles", amount_eur: "5.00", quantity: 5 }] },
    } as unknown as CaptainChatResponse);
    render(
      <I18nextProvider i18n={i18n}>
        <EscalesPanel milestoneId="dep-mayotte" />
      </I18nextProvider>,
    );
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "Two batches of miles" } });
    fireEvent.submit(screen.getByRole("textbox").closest("form")!);
    await screen.findByTestId("captain-cart");
    const [first, second] = screen.getAllByTestId("fake-paypal");
    authorized = milePledge({ id: "p-mile-1" });
    fireEvent.click(first);
    authorized = milePledge({ id: "p-mile-2", order_id: "ORDER-2" });
    fireEvent.click(second);
    await waitFor(() => expect(screen.getAllByTestId("mile-certificate-receipt")).toHaveLength(2));
    expect(escalesApi.issueMileCertificate).toHaveBeenCalledWith("p-mile-1", "ORDER-1", "Ada", "en");
    expect(escalesApi.issueMileCertificate).toHaveBeenCalledWith("p-mile-2", "ORDER-2", "Ada", "en");
  });

  it("hands the PayPal button one stable function, so the buttons are not redrawn", async () => {
    authorized = milePledge();
    await askAndPay();
    await screen.findByTestId("mile-certificate-receipt");
    expect(seenCallbacks.length).toBeGreaterThan(1);
    expect(new Set(seenCallbacks).size).toBe(1);
  });
});

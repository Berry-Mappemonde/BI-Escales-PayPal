import { render, screen, waitFor } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import { fetchCrewSupporterPlan, fetchPayPalDisputes, fetchPayPalInvoices, fetchPayPalSubscriptions } from "../api/escales";
import { TreasurerPayPalPanel } from "./TreasurerPayPalPanel";

vi.mock("../api/escales", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/escales")>();
  return {
    ...actual,
    fetchPayPalDisputes: vi.fn().mockResolvedValue({ paypal: { items: [] } }),
    fetchPayPalInvoices: vi.fn().mockResolvedValue({ paypal: { items: [] } }),
    fetchPayPalSubscriptions: vi.fn().mockResolvedValue({ items: [] }),
    fetchCrewSupporterPlan: vi.fn(),
    setupCrewSubscription: vi.fn(),
  };
});

describe("TreasurerPayPalPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchPayPalDisputes).mockResolvedValue({ paypal: { items: [] } });
    vi.mocked(fetchPayPalInvoices).mockResolvedValue({ paypal: { items: [] } });
    vi.mocked(fetchPayPalSubscriptions).mockResolvedValue({ items: [] });
  });

  it("shows a neutral hint when the crew plan id is not published", async () => {
    await i18n.changeLanguage("en");
    vi.mocked(fetchCrewSupporterPlan).mockResolvedValue({ plan_id: null });

    render(
      <I18nextProvider i18n={i18n}>
        <TreasurerPayPalPanel adminKey="sandbox-admin" />
      </I18nextProvider>,
    );

    const hint = await screen.findByTestId("treasurer-crew-plan-missing-hint");
    expect(hint).toHaveClass("hint");
    expect(hint).not.toHaveClass("error");
    await waitFor(() => {
      expect(fetchCrewSupporterPlan).toHaveBeenCalled();
    });
  });
});

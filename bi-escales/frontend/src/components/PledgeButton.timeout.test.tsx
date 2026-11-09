import { act, fireEvent, render, screen } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import { createPledge } from "../api/escales";
import { PLEDGE_CREATE_TIMEOUT_MS } from "../paypal/pledgeCreate";
import { PledgeButton } from "./PledgeButton";

vi.mock("../api/escales", () => ({
  createPledge: vi.fn(),
  registerVault: vi.fn(),
  authorizePledge: vi.fn(),
  fetchPledgeMode: vi.fn().mockResolvedValue({ payment_mode: "AUTHORIZE" }),
  fetchFeatures: vi.fn().mockResolvedValue({ card_fields: false }),
  isVaultPledge: () => false,
}));

const values = {
  amount_eur: "1.00",
  description: "test",
  milestone_id: "dep-mayotte",
  kind: "mile",
  target_id: "dep-mayotte",
};

describe("PledgeButton create pledge timeout", () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    vi.useFakeTimers();
    await i18n.changeLanguage("en");
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows a translated error and retry after the pledge POST exceeds 20s", async () => {
    vi.mocked(createPledge).mockImplementation(
      () => new Promise(() => {
        /* never resolves */
      }),
    );

    render(
      <I18nextProvider i18n={i18n}>
        <PledgeButton values={values} />
      </I18nextProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: i18n.t("pledge.create") }));
    expect(screen.getByText(i18n.t("pledge.creating"))).toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(PLEDGE_CREATE_TIMEOUT_MS);
      await Promise.resolve();
    });

    expect(screen.getByText(new RegExp(i18n.t("pledge.createTimeout")))).toBeInTheDocument();
    expect(screen.getByTestId("pledge-retry")).toBeInTheDocument();
    expect(screen.queryByText(i18n.t("pledge.creating"))).toBeNull();

    fireEvent.click(screen.getByTestId("pledge-retry"));
    expect(screen.queryByText(new RegExp(i18n.t("pledge.createTimeout")))).toBeNull();
    expect(screen.getByRole("button", { name: i18n.t("pledge.create") })).not.toBeDisabled();
  });
});

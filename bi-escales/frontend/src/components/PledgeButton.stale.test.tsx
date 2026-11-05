import { act, fireEvent, render, screen } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import { createPledge } from "../api/escales";
import type { PublicPledge } from "../api/types";
import { PledgeButton } from "./PledgeButton";

vi.mock("../api/escales", () => ({
  createPledge: vi.fn(),
  registerVault: vi.fn(),
  authorizePledge: vi.fn(),
  fetchFeatures: vi.fn().mockResolvedValue({ card_fields: false }),
  isVaultPledge: () => false,
}));

const base = {
  amount_eur: "20.00",
  description: "20 milles",
  milestone_id: "dep-mayotte",
  kind: "mile",
  target_id: "dep-mayotte",
};

function pledgeFor(token: string, amount: string): PublicPledge {
  return {
    id: `pledge-${token}`,
    status: "created",
    intent: "AUTHORIZE",
    currency: "EUR",
    amount_eur: amount,
    description: base.description,
    milestone_id: base.milestone_id,
    approve_link: `https://www.sandbox.paypal.com/checkoutnow?token=${token}`,
  } as PublicPledge;
}

describe("PledgeButton stale order responses", () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    await i18n.changeLanguage("en");
  });

  it("drops an order answered for an older amount", async () => {
    let resolveOld: (p: PublicPledge) => void = () => {};
    vi.mocked(createPledge)
      .mockImplementationOnce(() => new Promise<PublicPledge>((resolve) => (resolveOld = resolve)))
      .mockResolvedValueOnce(pledgeFor("NEW30", "30.00"));

    const view = render(
      <I18nextProvider i18n={i18n}>
        <PledgeButton values={base} />
      </I18nextProvider>,
    );
    const create = () => screen.getByRole("button", { name: i18n.t("pledge.create") });
    fireEvent.click(create());

    view.rerender(
      <I18nextProvider i18n={i18n}>
        <PledgeButton values={{ ...base, amount_eur: "30.00" }} />
      </I18nextProvider>,
    );
    fireEvent.click(create());
    const link = await screen.findByTestId("paypal-approve-link");
    expect(link).toHaveAttribute("href", expect.stringContaining("NEW30"));

    await act(async () => {
      resolveOld(pledgeFor("OLD20", "20.00"));
      await Promise.resolve();
    });
    expect(screen.getByTestId("paypal-approve-link")).toHaveAttribute("href", expect.stringContaining("NEW30"));
    expect(screen.queryByText(/OLD20/)).toBeNull();
  });

  it("hides an old approve link once the amount changes", async () => {
    let resolveOld: (p: PublicPledge) => void = () => {};
    vi.mocked(createPledge).mockImplementationOnce(
      () => new Promise<PublicPledge>((resolve) => (resolveOld = resolve)),
    );
    const view = render(
      <I18nextProvider i18n={i18n}>
        <PledgeButton values={base} />
      </I18nextProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: i18n.t("pledge.create") }));
    view.rerender(
      <I18nextProvider i18n={i18n}>
        <PledgeButton values={{ ...base, amount_eur: "45.00" }} />
      </I18nextProvider>,
    );
    await act(async () => {
      resolveOld(pledgeFor("OLD20", "20.00"));
      await Promise.resolve();
    });
    expect(screen.queryByTestId("paypal-approve-link")).toBeNull();
    expect(screen.getByRole("button", { name: i18n.t("pledge.create") })).not.toBeDisabled();
  });
});

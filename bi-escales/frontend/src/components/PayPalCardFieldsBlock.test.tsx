import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import type { PublicPledge } from "../api/types";
import { formatCardFieldError, PayPalCardFieldsBlock } from "./PayPalCardFieldsBlock";
import { authorizePledge, createPledge, fetchPledgeMode, fetchPledgeStatus, registerVault } from "../api/escales";
import i18n from "../i18n";

function stubPledge(partial: Partial<PublicPledge> & Pick<PublicPledge, "id">): PublicPledge {
  return {
    status: "created",
    intent: "AUTHORIZE",
    currency: "EUR",
    amount_eur: "5.00",
    description: "5 miles",
    milestone_id: "dep-mayotte",
    ...partial,
  };
}
vi.mock("../api/escales", () => ({createPledge: vi.fn(), fetchPledgeMode: vi.fn(), fetchPledgeStatus: vi.fn(), authorizePledge: vi.fn(), registerVault: vi.fn(), isVaultPledge: (p: {payment_mode?: string}) => p.payment_mode === "VAULT"}));
const values = {amount_eur: "5.00", description: "5 miles", milestone_id: "dep-mayotte", kind: "mile"};
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(fetchPledgeStatus).mockRejectedValue(new Error("Status unavailable"));
  vi.mocked(fetchPledgeMode).mockResolvedValue({ payment_mode: "AUTHORIZE" });
  void i18n.changeLanguage("en");
});
function sdk(pending?: Promise<void>) {
  let callbacks: Record<string, () => Promise<string>> = {};
  const fields = [0,1,2].map(() => ({render: vi.fn().mockResolvedValue(undefined), close: vi.fn()}));
  if (pending) fields[0].render.mockReturnValue(pending);
  const CardFields = vi.fn((c) => {callbacks = c; return {isEligible: () => true, NumberField: () => fields[0], ExpiryField: () => fields[1], CVVField: () => fields[2], submit: async () => {await Promise.all([(callbacks.createOrder || callbacks.createVaultSetupToken)(), (callbacks.createOrder || callbacks.createVaultSetupToken)()]);}};});
  return {paypal: {CardFields}, fields, CardFields};
}
describe("Card Fields checkout", () => {
  it.each(["AUTHORIZE", "VAULT"])("passes only the %s callback and completes first submit", async (mode) => {
    vi.mocked(fetchPledgeMode).mockResolvedValue({payment_mode: mode as "AUTHORIZE" | "VAULT"});
    const pledge = stubPledge({
      id: "P",
      payment_mode: mode,
      order_id: "O",
      setup_token_id: "S",
      intent: mode === "VAULT" ? "VAULT" : "AUTHORIZE",
    });
    vi.mocked(createPledge).mockResolvedValue(pledge);
    vi.mocked(authorizePledge).mockResolvedValue(pledge);
    vi.mocked(registerVault).mockResolvedValue(pledge);
    const s = sdk(); const onAuthorized = vi.fn();
    render(<PayPalCardFieldsBlock values={values} appLang="en" paypal={s.paypal} onAuthorized={onAuthorized} />);
    await waitFor(() => expect(screen.getByTestId("paypal-card-submit")).toBeEnabled());
    const config = s.CardFields.mock.calls[0][0];
    expect(Object.keys(config)).toEqual([mode === "VAULT" ? "createVaultSetupToken" : "createOrder", "onApprove", "onError"]);
    await expect(config[mode === "VAULT" ? "createVaultSetupToken" : "createOrder"]()).rejects.toThrow("Press Pay");
    expect(createPledge).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("paypal-card-submit"));
    await waitFor(() => expect(onAuthorized).toHaveBeenCalledWith(pledge));
    expect(createPledge).toHaveBeenCalledTimes(1);
    expect(createPledge).toHaveBeenCalledWith(expect.objectContaining({checkout_method:"card"}), expect.any(String));
    if (mode === "VAULT") {expect(registerVault).toHaveBeenCalledWith("P", "S");expect(authorizePledge).not.toHaveBeenCalled();}
    else {expect(authorizePledge).toHaveBeenCalledWith("P");expect(registerVault).not.toHaveBeenCalled();}
  });
  it("closes all rendered fields on unmount", async () => {
    vi.mocked(createPledge).mockResolvedValue(stubPledge({ id: "P", order_id: "O" }));
    const s = sdk();
    const view=render(<PayPalCardFieldsBlock values={values} appLang="en" paypal={s.paypal} />);
    await waitFor(() => expect(screen.getByTestId("paypal-card-submit")).toBeEnabled());view.unmount();
    for (const f of s.fields) expect(f.close).toHaveBeenCalledTimes(1);
  });
  it("stops rendering subsequent fields when closed during rendering", async () => {
    let finish!: () => void;const pending=new Promise<void>(r => {finish=r;});
    vi.mocked(createPledge).mockResolvedValue(stubPledge({ id: "P", order_id: "O" }));
    const s = sdk(pending);
    const view=render(<PayPalCardFieldsBlock values={values} appLang="en" paypal={s.paypal} />);
    await waitFor(() => expect(s.fields[0].render).toHaveBeenCalled());view.unmount();await act(async () => finish());
    expect(s.fields[0].close).toHaveBeenCalledTimes(1);expect(s.fields[1].render).not.toHaveBeenCalled();expect(s.fields[2].render).not.toHaveBeenCalled();
  });
  it("renders and edits amount, quantity and contributor without creating pledges", async () => {
    const s=sdk(); const view=render(<PayPalCardFieldsBlock values={values} appLang="en" paypal={s.paypal} />);
    await waitFor(() => expect(screen.getByTestId("paypal-card-submit")).toBeEnabled());
    const edited={...values,amount_eur:"9.00",quantity:9,contributor:"Alice"};
    view.rerender(<PayPalCardFieldsBlock values={edited} appLang="en" paypal={s.paypal} />);
    await waitFor(() => expect(screen.getByTestId("paypal-card-submit")).toBeEnabled());
    expect(createPledge).not.toHaveBeenCalled();expect(s.CardFields).toHaveBeenCalledTimes(1);
    vi.mocked(createPledge).mockResolvedValue(stubPledge({ id: "P", order_id: "O" }));
    vi.mocked(authorizePledge).mockResolvedValue(stubPledge({ id: "P", status: "authorized" }));
    fireEvent.click(screen.getByTestId("paypal-card-submit"));
    await waitFor(() => expect(authorizePledge).toHaveBeenCalledWith("P"));
    expect(createPledge).toHaveBeenCalledTimes(1);
    expect(createPledge).toHaveBeenCalledWith(expect.objectContaining(edited),expect.any(String));
  });
  it("does not configure fields or create a pledge when mode lookup fails", async () => {
    vi.mocked(fetchPledgeMode).mockRejectedValue(new Error("Mode unavailable"));const s=sdk();
    render(<PayPalCardFieldsBlock values={values} appLang="en" paypal={s.paypal} />);
    await screen.findByText(/Mode unavailable/);
    expect(createPledge).not.toHaveBeenCalled();expect(s.CardFields).not.toHaveBeenCalled();
  });

  it("reuses the client key after a failed creation without posting on edits", async () => {
    vi.mocked(createPledge)
      .mockRejectedValueOnce(new Error("Network unavailable"))
      .mockResolvedValue(stubPledge({ id: "P", order_id: "O" }));
    vi.mocked(authorizePledge).mockResolvedValue(stubPledge({ id: "P", status: "authorized" }));
    const s = sdk();
    const done = vi.fn();
    render(<PayPalCardFieldsBlock values={values} appLang="en" paypal={s.paypal} onAuthorized={done} />);
    await waitFor(() => expect(screen.getByTestId("paypal-card-submit")).toBeEnabled());
    fireEvent.click(screen.getByTestId("paypal-card-submit"));await screen.findByText(/Network unavailable/);
    fireEvent.click(screen.getByTestId("paypal-card-submit"));await waitFor(() => expect(done).toHaveBeenCalled());
    expect(createPledge).toHaveBeenCalledTimes(2);
    expect(vi.mocked(createPledge).mock.calls[0][1]).toBe(vi.mocked(createPledge).mock.calls[1][1]);
  });

});

it("retries authorization without creating another pledge", async () => {
  const pledge = stubPledge({ id: "P", order_id: "O", status: "authorized" });
  vi.mocked(createPledge).mockResolvedValue(pledge);
  vi.mocked(authorizePledge).mockRejectedValueOnce(new Error("Authorization unavailable")).mockResolvedValue(pledge);
  const s = sdk();
  const done = vi.fn();
  render(<PayPalCardFieldsBlock values={values} appLang="en" paypal={s.paypal} onAuthorized={done} />);
  const button = screen.getByTestId("paypal-card-submit");
  await waitFor(() => expect(button).toBeEnabled());
  fireEvent.click(button);
  await screen.findByText(/Authorization unavailable/);
  fireEvent.click(button);
  await waitFor(() => expect(done).toHaveBeenCalledWith(pledge));
  expect(createPledge).toHaveBeenCalledTimes(1);
  expect(authorizePledge).toHaveBeenCalledTimes(2);
});

it("does not configure fields after closing during the mode lookup", async () => {
  let finish!: (mode: { payment_mode: "AUTHORIZE" }) => void;
  vi.mocked(fetchPledgeMode).mockReturnValue(new Promise((resolve) => { finish = resolve; }));
  const s = sdk();
  const view = render(<PayPalCardFieldsBlock values={values} appLang="en" paypal={s.paypal} />);
  view.unmount();
  await act(async () => { finish({ payment_mode: "AUTHORIZE" }); });
  expect(s.CardFields).not.toHaveBeenCalled();
  expect(createPledge).not.toHaveBeenCalled();
});

it("does not authorize a pledge returned after checkout closes", async () => {
  let finish!: (pledge: PublicPledge) => void;
  vi.mocked(createPledge).mockReturnValue(new Promise((resolve) => { finish = resolve; }));
  const s = sdk();
  const done = vi.fn();
  const view = render(<PayPalCardFieldsBlock values={values} appLang="en" paypal={s.paypal} onAuthorized={done} />);
  await waitFor(() => expect(screen.getByTestId("paypal-card-submit")).toBeEnabled());
  fireEvent.click(screen.getByTestId("paypal-card-submit"));
  view.unmount();
  await act(async () => { finish(stubPledge({ id: "P", order_id: "O" })); });
  expect(createPledge).toHaveBeenCalledTimes(1);
  expect(authorizePledge).not.toHaveBeenCalled();
  expect(registerVault).not.toHaveBeenCalled();
  expect(done).not.toHaveBeenCalled();
  for (const field of s.fields) expect(field.close).toHaveBeenCalledTimes(1);
});

it("does not report an authorization completed after checkout closes", async () => {
  let finish!: (pledge: PublicPledge) => void;
  vi.mocked(createPledge).mockResolvedValue(stubPledge({ id: "P", order_id: "O" }));
  vi.mocked(authorizePledge).mockReturnValue(new Promise((resolve) => { finish = resolve; }));
  const s = sdk();
  const done = vi.fn();
  const view = render(<PayPalCardFieldsBlock values={values} appLang="en" paypal={s.paypal} onAuthorized={done} />);
  await waitFor(() => expect(screen.getByTestId("paypal-card-submit")).toBeEnabled());
  fireEvent.click(screen.getByTestId("paypal-card-submit"));
  await waitFor(() => expect(authorizePledge).toHaveBeenCalled());
  view.unmount();
  await act(async () => { finish(stubPledge({ id: "P", status: "authorized" })); });
  expect(done).not.toHaveBeenCalled();
});

describe("card confirm UI", () => {
  const pledgeId = "pledge01-test-id";

  async function completeCheckout(
    mode: "AUTHORIZE" | "VAULT",
    lang: "en" | "fr",
    kind = "mile",
  ) {
    await i18n.changeLanguage(lang);
    vi.mocked(fetchPledgeMode).mockResolvedValue({ payment_mode: mode });
    const pledge = stubPledge({
      id: pledgeId,
      payment_mode: mode,
      kind,
      order_id: "O",
      setup_token_id: "S",
      intent: mode === "VAULT" ? "VAULT" : "AUTHORIZE",
    });
    vi.mocked(createPledge).mockResolvedValue(pledge);
    vi.mocked(authorizePledge).mockResolvedValue(pledge);
    vi.mocked(registerVault).mockResolvedValue(pledge);
    const s = sdk();
    const onAuthorized = vi.fn();
    const formValues = { ...values, kind };
    const view = render(
      <PayPalCardFieldsBlock values={formValues} appLang={lang} paypal={s.paypal} onAuthorized={onAuthorized} />,
    );
    await waitFor(() => expect(screen.getByTestId("paypal-card-submit")).toBeEnabled());
    fireEvent.click(screen.getByTestId("paypal-card-submit"));
    await waitFor(() => expect(onAuthorized).toHaveBeenCalled());
    return { onAuthorized, view, formValues, paypal: s.paypal };
  }

  it.each([
    ["AUTHORIZE", "en", /Card payment confirmed — pledge authorized/, /Reference: pledge01/, /boat arrives at this stop/],
    ["VAULT", "en", /Card payment confirmed — payment method saved/, /Reference: pledge01/, /boat arrives at this stop/],
    ["AUTHORIZE", "fr", /Paiement carte confirmé — promesse autorisée/, /Référence : pledge01/, /arrivée du bateau/],
    ["VAULT", "fr", /Paiement carte confirmé — moyen de paiement enregistré/, /Référence : pledge01/, /arrivée du bateau/],
  ] as const)("shows mile %s success copy in %s", async (mode, lang, title, refLine, nextLine) => {
    await completeCheckout(mode, lang, "mile");
    expect(screen.getByTestId("paypal-card-confirm")).toBeInTheDocument();
    expect(screen.getByTestId("paypal-card-confirm-ref")).toHaveTextContent(refLine);
    expect(screen.getByTestId("paypal-card-confirm-next")).toHaveTextContent(nextLine);
    expect(screen.getByTestId("paypal-card-confirm")).toHaveTextContent(title);
    expect(screen.getByTestId("paypal-card-checkout")).toHaveAttribute("hidden");
    expect(screen.getByTestId("paypal-card-submit")).not.toBeVisible();
  });

  it("shows cabin_leg AUTHORIZE next copy (leg departure, not stop arrival)", async () => {
    await completeCheckout("AUTHORIZE", "en", "cabin_leg");
    expect(screen.getByTestId("paypal-card-confirm")).toHaveTextContent(/pledge authorized/i);
    expect(screen.getByTestId("paypal-card-confirm-next")).toHaveTextContent(/when this leg departs/);
    expect(screen.getByTestId("paypal-card-confirm-next")).not.toHaveTextContent(/treasurer/i);
  });

  it("shows mile VAULT stop arrival copy (treasurer approval)", async () => {
    await completeCheckout("VAULT", "en", "mile");
    expect(screen.getByTestId("paypal-card-confirm")).toHaveTextContent(/payment method saved/i);
    expect(screen.getByTestId("paypal-card-confirm-next")).toHaveTextContent(/treasurer approves/);
    expect(screen.getByTestId("paypal-card-confirm-next")).not.toHaveTextContent(/leg departs/i);
  });

  it("keeps confirmation when appLang changes after success", async () => {
    const { view, formValues, paypal } = await completeCheckout("AUTHORIZE", "en", "mile");
    expect(screen.getByTestId("paypal-card-confirm")).toBeInTheDocument();
    await i18n.changeLanguage("fr");
    view.rerender(
      <PayPalCardFieldsBlock values={formValues} appLang="fr" paypal={paypal} />,
    );
    await waitFor(() => {
      expect(screen.getByTestId("paypal-card-confirm")).toBeInTheDocument();
    });
    expect(screen.getByTestId("paypal-card-submit")).not.toBeVisible();
    expect(screen.getByTestId("paypal-card-confirm-next")).toHaveTextContent(/arrivée du bateau/);
  });

  it("maps INVALID_EXPIRY to a readable message", () => {
    expect(formatCardFieldError("INVALID_EXPIRY", i18n.t)).toMatch(/expiry|expiration/i);
  });

  it("restores the pay button after a failed submit", async () => {
    vi.mocked(createPledge).mockResolvedValue(stubPledge({ id: pledgeId, order_id: "O" }));
    vi.mocked(authorizePledge).mockRejectedValueOnce(new Error("Authorization unavailable"));
    const s = sdk();
    render(<PayPalCardFieldsBlock values={values} appLang="en" paypal={s.paypal} />);
    const button = screen.getByTestId("paypal-card-submit");
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);
    await screen.findByText(/Authorization unavailable/);
    await waitFor(() => expect(button).toBeEnabled());
    expect(button).toHaveTextContent(/Pay with card/);
    expect(screen.getByTestId("paypal-card-fields")).toHaveTextContent(/Pledge error/);
  });

  it("ignores a second Pay click while checkout is in flight", async () => {
    let finishCardSubmit!: () => void;
    const cardSubmit = new Promise<void>((resolve) => {
      finishCardSubmit = resolve;
    });
    const pledge = stubPledge({ id: pledgeId, order_id: "O" });
    vi.mocked(createPledge).mockResolvedValue(pledge);
    vi.mocked(authorizePledge).mockImplementation(
      () => new Promise((resolve) => setTimeout(() => resolve(pledge), 0)),
    );
    let callbacks: Record<string, () => Promise<string>> = {};
    const fields = [0, 1, 2].map(() => ({ render: vi.fn().mockResolvedValue(undefined), close: vi.fn() }));
    const CardFields = vi.fn((c) => {
      callbacks = c;
      return {
        isEligible: () => true,
        NumberField: () => fields[0],
        ExpiryField: () => fields[1],
        CVVField: () => fields[2],
        submit: async () => {
          await cardSubmit;
          await (callbacks.createOrder || callbacks.createVaultSetupToken)?.();
        },
      };
    });
    const onAuthorized = vi.fn();
    render(
      <PayPalCardFieldsBlock values={values} appLang="en" paypal={{ CardFields }} onAuthorized={onAuthorized} />,
    );
    const button = screen.getByTestId("paypal-card-submit");
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);
    await waitFor(() => expect(button).toBeDisabled());
    fireEvent.click(button);
    await act(async () => {
      finishCardSubmit();
    });
    await waitFor(() => expect(onAuthorized).toHaveBeenCalledTimes(1));
    expect(createPledge).toHaveBeenCalledTimes(1);
    expect(authorizePledge).toHaveBeenCalledTimes(1);
  });
});

it.each(["en", "fr"])("shows paid-now confirmation for an immediate card donation in %s", async lang => {
  await i18n.changeLanguage(lang);
  vi.mocked(fetchPledgeMode).mockResolvedValue({ payment_mode: "CAPTURE" });
  vi.mocked(createPledge).mockResolvedValue(stubPledge({ id: "DONATION", kind: "project_pledge", payment_mode: "CAPTURE", order_id: "CARD-ORDER" }));
  vi.mocked(authorizePledge).mockResolvedValue(stubPledge({ id: "DONATION", kind: "project_pledge", payment_mode: "CAPTURE", status: "captured" }));
  const s = sdk();
  render(<PayPalCardFieldsBlock values={{ ...values, kind: "project_pledge" }} appLang={lang} paypal={s.paypal} />);
  expect(await screen.findByText(lang === "en" ? /charged immediately after approval/ : /débité immédiatement après approbation/)).toBeInTheDocument();
  await waitFor(() => expect(screen.getByTestId("paypal-card-submit")).toBeEnabled());
  fireEvent.click(screen.getByTestId("paypal-card-submit"));
  expect(await screen.findByText(lang === "en" ? "Donation paid" : "Don payé")).toBeInTheDocument();
  expect(screen.getByTestId("paypal-card-confirm-next")).toHaveTextContent(lang === "en" ? "Charged now" : "Débité maintenant");
  expect(screen.queryByText(/pledge authorized|promesse autorisée/i)).toBeNull();
});

it("never presents a declined capture receipt as paid", async () => {
  vi.mocked(fetchPledgeMode).mockResolvedValue({ payment_mode: "CAPTURE" });
  vi.mocked(createPledge).mockResolvedValue(stubPledge({ id: "DECLINED", kind: "project_pledge", payment_mode: "CAPTURE", order_id: "CARD-ORDER" }));
  vi.mocked(authorizePledge).mockResolvedValue(stubPledge({ id: "DECLINED", kind: "project_pledge", payment_mode: "CAPTURE", status: "capture_failed" }));
  const done = vi.fn(); const s = sdk();
  render(<PayPalCardFieldsBlock values={{ ...values, kind: "project_pledge" }} appLang="en" paypal={s.paypal} onAuthorized={done} />);
  await waitFor(() => expect(screen.getByTestId("paypal-card-submit")).toBeEnabled());
  fireEvent.click(screen.getByTestId("paypal-card-submit"));
  await screen.findByText(/Donation payment has not completed/);
  expect(screen.queryByTestId("paypal-card-confirm")).toBeNull();
  expect(done).not.toHaveBeenCalled();
});

it("does not capture after a card SDK error even if submit resolves", async () => {
  vi.mocked(createPledge).mockResolvedValue(stubPledge({ id: "ERROR", order_id: "CARD-ORDER" }));
  const fields = { render: async () => {}, close: async () => {} };
  const CardFields = (config: Record<string, (...args: any[]) => any>) => ({ isEligible: () => true,
    NumberField: () => fields, ExpiryField: () => fields, CVVField: () => fields,
    submit: async () => { await config.createOrder(); config.onError(); } });
  render(<PayPalCardFieldsBlock values={values} appLang="en" paypal={{ CardFields } as never} />);
  await waitFor(() => expect(screen.getByTestId("paypal-card-submit")).toBeEnabled());
  fireEvent.click(screen.getByTestId("paypal-card-submit"));
  await screen.findByText(/Card confirmation failed/);
  expect(authorizePledge).not.toHaveBeenCalled();
});

it.each(["en", "fr"])("keeps a pending payment distinct from paid and prevents repaying in %s", async lang => {
  await i18n.changeLanguage(lang);
  vi.mocked(fetchPledgeMode).mockResolvedValue({ payment_mode: "CAPTURE" });
  vi.mocked(createPledge).mockResolvedValue(stubPledge({ id: "PENDING", payment_mode: "CAPTURE", order_id: "PENDING-ORDER" }));
  vi.mocked(authorizePledge).mockResolvedValue(stubPledge({ id: "PENDING", payment_mode: "CAPTURE", status: "pending" }));
  const s = sdk();
  render(<PayPalCardFieldsBlock values={{ ...values, kind: "project_pledge" }} appLang={lang} paypal={s.paypal} />);
  await waitFor(() => expect(screen.getByTestId("paypal-card-submit")).toBeEnabled());
  fireEvent.click(screen.getByTestId("paypal-card-submit"));
  expect(await screen.findByText(lang === "en" ? "Payment pending" : "Paiement en attente")).toBeInTheDocument();
  expect(screen.getByTestId("paypal-card-confirm-next")).toHaveTextContent(lang === "en" ? "Do not pay again" : "Ne payez pas à nouveau");
  expect(screen.getByTestId("paypal-card-confirm")).not.toHaveTextContent(/try again|réessay|Donation paid|Don payé/i);
  expect(screen.getByTestId("paypal-card-submit")).not.toBeVisible();
  expect(createPledge).toHaveBeenCalledTimes(1);
});

it.each([true, false])("starts a new order and request ID after an explicit decline (HTTP error: %s)", async httpError => {
  vi.mocked(fetchPledgeMode).mockResolvedValue({ payment_mode: "CAPTURE" });
  const first = stubPledge({ id: "DECLINED", payment_mode: "CAPTURE", order_id: "ORDER-OLD" });
  const second = stubPledge({ id: "RETRY", payment_mode: "CAPTURE", order_id: "ORDER-NEW" });
  vi.mocked(createPledge).mockResolvedValueOnce(first).mockResolvedValueOnce(second);
  if (httpError) {
    vi.mocked(authorizePledge).mockRejectedValueOnce(new Error("PayPal capture status DECLINED"));
    vi.mocked(fetchPledgeStatus).mockResolvedValue({ status: "capture_failed" });
  } else {
    vi.mocked(authorizePledge).mockResolvedValueOnce({ ...first, status: "capture_failed" });
  }
  vi.mocked(authorizePledge).mockResolvedValueOnce({ ...second, status: "captured" });
  const s = sdk();
  render(<PayPalCardFieldsBlock values={{ ...values, kind: "project_pledge" }} appLang="en" paypal={s.paypal} />);
  const button = screen.getByTestId("paypal-card-submit");
  await waitFor(() => expect(button).toBeEnabled());
  fireEvent.click(button);
  await screen.findByText(/Donation payment has not completed/);
  fireEvent.click(button);
  await screen.findByText("Donation paid");
  expect(createPledge).toHaveBeenCalledTimes(2);
  expect(vi.mocked(createPledge).mock.calls[0][1]).not.toBe(vi.mocked(createPledge).mock.calls[1][1]);
  expect(vi.mocked(authorizePledge).mock.calls).toEqual([["DECLINED"], ["RETRY"]]);
});

it("resolves a lost capture response as pending without offering another payment", async () => {
  vi.mocked(fetchPledgeMode).mockResolvedValue({ payment_mode: "CAPTURE" });
  vi.mocked(createPledge).mockResolvedValue(stubPledge({ id: "LOST", payment_mode: "CAPTURE", order_id: "ORDER" }));
  vi.mocked(authorizePledge).mockRejectedValue(new Error("Network unavailable"));
  vi.mocked(fetchPledgeStatus).mockResolvedValue({ status: "pending" });
  const s = sdk();
  render(<PayPalCardFieldsBlock values={{ ...values, kind: "project_pledge" }} appLang="en" paypal={s.paypal} />);
  await waitFor(() => expect(screen.getByTestId("paypal-card-submit")).toBeEnabled());
  fireEvent.click(screen.getByTestId("paypal-card-submit"));
  await screen.findByText("Payment pending");
  expect(screen.getByTestId("paypal-card-submit")).not.toBeVisible();
  expect(createPledge).toHaveBeenCalledTimes(1);
});

it("creates a fresh order after the card SDK reports an instrument decline", async () => {
  vi.mocked(fetchPledgeMode).mockResolvedValue({ payment_mode: "CAPTURE" });
  vi.mocked(createPledge)
    .mockResolvedValueOnce(stubPledge({ id: "DECLINED-SDK", payment_mode: "CAPTURE", order_id: "OLD" }))
    .mockResolvedValueOnce(stubPledge({ id: "NEW-SDK", payment_mode: "CAPTURE", order_id: "NEW" }));
  vi.mocked(authorizePledge).mockResolvedValue(stubPledge({ id: "NEW-SDK", payment_mode: "CAPTURE", status: "captured" }));
  const fields = { render: async () => {}, close: async () => {} };
  let attempts = 0;
  const orders: string[] = [];
  const CardFields = (config: Record<string, (...args: any[]) => any>) => ({ isEligible: () => true,
    NumberField: () => fields, ExpiryField: () => fields, CVVField: () => fields,
    submit: async () => {
      orders.push(await config.createOrder());
      if (attempts++ === 0) config.onError({ details: [{ issue: "INSTRUMENT_DECLINED" }] });
    } });
  render(<PayPalCardFieldsBlock values={{ ...values, kind: "project_pledge" }} appLang="en" paypal={{ CardFields } as never} />);
  const button = screen.getByTestId("paypal-card-submit");
  await waitFor(() => expect(button).toBeEnabled());
  fireEvent.click(button);
  await screen.findByText(/Card confirmation failed/);
  fireEvent.click(button);
  await screen.findByText("Donation paid");
  expect(orders).toEqual(["OLD", "NEW"]);
  expect(vi.mocked(createPledge).mock.calls[0][1]).not.toBe(vi.mocked(createPledge).mock.calls[1][1]);
  expect(authorizePledge).toHaveBeenCalledTimes(1);
  expect(authorizePledge).toHaveBeenCalledWith("NEW-SDK");
});

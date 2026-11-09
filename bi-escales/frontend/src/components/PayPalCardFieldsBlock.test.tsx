import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import type { PublicPledge } from "../api/types";
import { PayPalCardFieldsBlock } from "./PayPalCardFieldsBlock";
import { authorizePledge, createPledge, fetchPledgeMode, registerVault } from "../api/escales";
import "../i18n";

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
vi.mock("../api/escales", () => ({createPledge: vi.fn(), fetchPledgeMode: vi.fn(), authorizePledge: vi.fn(), registerVault: vi.fn(), isVaultPledge: (p: {payment_mode?: string}) => p.payment_mode === "VAULT"}));
const values = {amount_eur: "5.00", description: "5 miles", milestone_id: "dep-mayotte", kind: "mile"};
beforeEach(() => {vi.clearAllMocks(); vi.mocked(fetchPledgeMode).mockResolvedValue({payment_mode:"AUTHORIZE"});});
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

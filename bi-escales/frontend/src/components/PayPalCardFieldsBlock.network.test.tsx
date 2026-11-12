import { StrictMode, useState } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import type { PayPalNamespace } from "../paypal/paypalSdk";
import { PayPalCardFieldsBlock } from "./PayPalCardFieldsBlock";
import "../i18n";

afterEach(() => vi.unstubAllGlobals());

it.each(["AUTHORIZE", "VAULT"])("posts no %s pledge until Pay, then posts once with edited values", async (mode) => {
  const user = userEvent.setup();
  const pledge = {
    id: "P", payment_mode: mode, order_id: "ORDER", setup_token_id: "SETUP",
  };
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = new URL(String(input), "http://localhost").pathname;
    if (path === "/api/escales/pledges/mode" && !init?.method) {
      return { ok: true, json: async () => ({ payment_mode: mode }) };
    }
    if (init?.method === "POST" && [
      "/api/escales/pledges", "/api/escales/pledges/P/authorize", "/api/escales/pledges/P/vault",
    ].includes(path)) {
      return { ok: true, json: async () => pledge };
    }
    throw new Error(`Unexpected request: ${init?.method} ${path}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  const done = vi.fn();
  const field = () => ({ render: vi.fn().mockResolvedValue(undefined), close: vi.fn() });
  const CardFields = vi.fn((config: Record<string, () => Promise<string>>) => ({
    isEligible: () => true,
    NumberField: field,
    ExpiryField: field,
    CVVField: field,
    submit: async () => {
      const create = config.createOrder || config.createVaultSetupToken;
      const tokens = await Promise.all([create(), create()]);
      expect(tokens).toEqual(mode === "VAULT" ? ["SETUP", "SETUP"] : ["ORDER", "ORDER"]);
    },
  }));
  const paypal = { CardFields };
  function Form() {
    const [quantity, setQuantity] = useState(1);
    const [contributor, setContributor] = useState("");
    return <>
      <label>Quantity<input type="number" value={quantity} onChange={(e) => setQuantity(Number(e.target.value))} /></label>
      <label>Contributor<input value={contributor} onChange={(e) => setContributor(e.target.value)} /></label>
      <PayPalCardFieldsBlock
        paypal={paypal as unknown as PayPalNamespace} appLang="en" onAuthorized={done}
        values={{
          quantity, contributor, amount_eur: `${quantity}.00`,
          description: `${quantity} miles`, milestone_id: "dep-mayotte", kind: "mile",
        }}
      />
    </>;
  }
  render(<StrictMode><Form /></StrictMode>);
  const button = screen.getByTestId("paypal-card-submit");
  await waitFor(() => expect(button).toBeEnabled());
  const posts = () => fetchMock.mock.calls.filter(([input, init]) => (
    new URL(String(input), "http://localhost").pathname === "/api/escales/pledges" && init?.method === "POST"
  ));
  expect(posts()).toHaveLength(0);
  await user.clear(screen.getByLabelText("Quantity"));
  await user.type(screen.getByLabelText("Quantity"), "12");
  await user.type(screen.getByLabelText("Contributor"), "Alice");
  expect(posts()).toHaveLength(0);
  await user.click(button);
  await waitFor(() => expect(done).toHaveBeenCalledWith(pledge));
  expect(posts()).toHaveLength(1);
  const init = posts()[0][1]!;
  expect(JSON.parse(String(init.body))).toMatchObject({
    quantity: 12, amount_eur: "12.00", contributor: "Alice", checkout_method: "card",
  });
  expect(init.headers).toMatchObject({ "PayPal-Request-Id": expect.any(String) });
  expect(Object.keys(CardFields.mock.calls[0][0])).toEqual([
    mode === "VAULT" ? "createVaultSetupToken" : "createOrder",
    "onApprove",
    "onError",
    "onCancel",
    "billingAddress",
  ]);
});

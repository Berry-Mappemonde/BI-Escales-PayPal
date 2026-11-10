import "../i18n";
import { render, waitFor, screen, act } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { PledgeButton } from "./PledgeButton";
import { authorizePledge } from "../api/escales";
let callbacks: Record<string, any>;
vi.mock("../api/escales", () => ({
  createPledge: vi.fn(async () => ({ id: "ORIGINAL", order_id: "ORDER", amount_eur: "20.00" })),
  authorizePledge: vi.fn(async () => ({ id: "ORIGINAL", status: "authorized", amount_eur: "20.00" })),
  registerVault: vi.fn(), fetchFeatures: vi.fn(async () => ({})), fetchPledgeMode: vi.fn(async () => ({ payment_mode: "AUTHORIZE" })), isVaultPledge: () => false,
}));
vi.mock("../paypal/paypalSdk", async load => ({ ...(await load<object>()), loadPayPalSdk: async () => ({ Buttons: (config: Record<string, any>) => { callbacks = config; return { render: async () => {}, close: async () => {} }; } }) }));
it("F02 reconciles the original approval after an amount/target edit without crediting the new form", async () => {
  vi.stubEnv("VITE_PAYPAL_CLIENT_ID", "audit-public-client");
  const notify = vi.fn(); const values = { amount_eur: "20.00", milestone_id: "old-stop", kind: "mile", target_id: "old-target", description: "Original" };
  const view = render(<PledgeButton values={values} onAuthorized={notify} />);
  await waitFor(() => expect(callbacks).toBeDefined()); const original = callbacks;
  await act(async () => { await original.createOrder(); });
  view.rerender(<PledgeButton values={{ ...values, amount_eur: "50.00", target_id: "new-target" }} onAuthorized={notify} />);
  await act(async () => { await original.onApprove({ orderId: "ORDER" }); });
  expect(authorizePledge).toHaveBeenCalledWith("ORIGINAL");
  expect(notify).not.toHaveBeenCalled();
  expect(await screen.findByText(/ORIGINAL.*20.00/)).toBeInTheDocument();
  vi.unstubAllEnvs();
});

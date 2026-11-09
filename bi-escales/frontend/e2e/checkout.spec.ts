import { expect, test } from "@playwright/test";

for (const scenario of ["authorize", "project", "card", "vault"]) {
test(`React ${scenario} checkout retains its v6 session while creation is pending`, async ({ page }) => {
  const calls: string[] = [];
  await page.route("http://127.0.0.1:5178/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/features")) return route.fulfill({ json: { card_fields: scenario === "card", wallet_pay: false } });
    if (path.endsWith("/pledges/mode")) return route.fulfill({ json: { payment_mode: scenario === "vault" ? "VAULT" : "AUTHORIZE" } });
    if (path.endsWith("/schedule")) return route.fulfill({ json: { legs: [] } });
    if (path.endsWith("/pledges")) {
      calls.push("create");
      await new Promise(resolve => setTimeout(resolve, 100));
      return route.fulfill({ json: { id: "PLEDGE", order_id: scenario === "vault" ? undefined : "ORDER", setup_token_id: scenario === "vault" ? "SETUP" : undefined, status: "created", amount_eur: "20.00", payment_mode: scenario === "vault" ? "VAULT" : "AUTHORIZE" } });
    }
    if (path.endsWith("/PLEDGE/authorize") || path.endsWith("/PLEDGE/vault")) {
      calls.push(scenario === "vault" ? "vault" : "authorize");
      return route.fulfill({ json: { id: "PLEDGE", order_id: "ORDER", status: scenario === "vault" ? "vaulted" : scenario === "project" ? "captured" : "authorized", amount_eur: "20.00" } });
    }
    throw new Error("Unexpected checkout API route");
  });
  await page.addInitScript(() => {
    const events: string[] = []; Object.assign(window, { sdkEvents: events });
    Object.assign(window, { paypal: { createInstance: async () => ({
      findEligibleMethods: async () => ({ isEligible: (name: string) => ["paypal", "advanced_cards"].includes(name) }),
      createCardFieldsOneTimePaymentSession: () => ({
        createCardFieldsComponent: () => Object.assign(document.createElement("div"), { destroy() {} }),
        submit: async () => { events.push("card-confirm"); return { state: "succeeded", data: { orderId: "ORDER" } }; },
        destroy() {},
      }),
      createPayPalSavePaymentSession: (callbacks: any) => ({
        start: async (_options: unknown, payment: Promise<{ vaultSetupToken: string }>) => {
          events.push("start"); const { vaultSetupToken } = await payment;
          events.push("created"); await callbacks.onApprove({ vaultSetupToken, fundingSource: "paypal" }); events.push("approved");
        },
        destroy: () => events.push("destroy"),
      }),
      createPayPalOneTimePaymentSession: (callbacks: any) => ({
        start: async (_options: unknown, payment: Promise<{ orderId: string }>) => {
          events.push("start");
          const { orderId } = await payment;
          events.push("created");
          await callbacks.onApprove({ orderId, fundingSource: "paypal" });
          events.push("approved");
        },
        destroy: () => events.push("destroy"),
      }),
    }) } });
  });
  await page.goto(`/e2e/checkout.html?scenario=${scenario}`);
  if (scenario === "card") {
    await page.getByTestId("paypal-card-submit").click();
  } else {
  const button = page.locator("paypal-button");
  await button.evaluate(element => { element.textContent = "PayPal TEST"; Object.assign((element as HTMLElement).style, { display: "block", width: "180px", height: "40px" }); });
  await button.click();
  }
  await expect(page.locator("#checkout")).toHaveAttribute("data-authorized", scenario === "vault" ? "vaulted" : scenario === "project" ? "captured" : "authorized");
  expect(calls).toEqual(["create", scenario === "vault" ? "vault" : "authorize"]);
  expect(await page.evaluate(() => (window as any).sdkEvents)).toEqual(scenario === "card" ? ["card-confirm"] : ["start", "created", "approved"]);
});

}

import { expect, test } from "@playwright/test";

for (const status of ["APPROVED", "PAYER_ACTION_REQUIRED"]) {
  test(`Google Pay ${status}: independent eligibility and native sheet ordering`, async ({ page }) => {
    await page.route("**/wallet-harness", route => route.fulfill({ contentType: "text/html", body: '<html><body><div id="wallet"></div></body></html>' }));
    await page.goto("/wallet-harness");
    await page.evaluate(async ({ status }) => {
      const { walletFactories } = await import(/* @vite-ignore */ "/src/paypal/paypalWallets.ts");
      const events: string[] = [];
      Object.assign(window, { walletEvents: events });
      let authorized: (data: unknown) => Promise<unknown>;
      Object.assign(window, { google: { payments: { api: { PaymentsClient: class {
        constructor(options: any) { if (options.environment !== "TEST") throw new Error("Sandbox required"); authorized = options.paymentDataCallbacks.onPaymentAuthorized; }
        async isReadyToPay() { return { result: true }; }
        createButton(options: any) { const button = document.createElement("button"); button.textContent = "Google Pay TEST"; button.onclick = options.onClick; return button; }
        async loadPaymentData() { await authorized({ paymentMethodData: {} }); events.push("sheet-closed"); return {}; }
      } } } } });
      const wallets = walletFactories({ createGooglePayOneTimePaymentSession: () => ({
        formatConfigForPaymentRequest: () => ({ apiVersion: 2, apiVersionMinor: 0, allowedPaymentMethods: [], merchantInfo: {}, countryCode: "FR" }),
        confirmOrder: async () => { events.push("confirm"); return { status, id: "MOCK-ORDER" }; },
        initiatePayerAction: async () => { events.push("3ds"); },
      }) }, { isEligible: (name: string) => name === "googlepay", getDetails: () => ({ config: {} }) });
      const options = { amount: "12.50", currencyCode: "EUR", createOrder: async () => { events.push("create"); return "MOCK-ORDER"; }, onApprove: async () => { events.push("server-approve"); } };
      try { await wallets.Applepay(options).render(document.createElement("div")); } catch { events.push("apple-ineligible"); }
      await wallets.Googlepay(options).render(document.querySelector<HTMLElement>("#wallet")!);
    }, { status });
    expect(await page.evaluate(() => (window as any).walletEvents)).toEqual(["apple-ineligible"]);
    await page.getByRole("button", { name: "Google Pay TEST" }).click();
    await expect.poll(() => page.evaluate(() => (window as any).walletEvents)).toEqual([
      "apple-ineligible", "create", "confirm", "sheet-closed", ...(status === "PAYER_ACTION_REQUIRED" ? ["3ds"] : []), "server-approve",
    ]);
  });
}

test("Apple Pay merchant validation and confirmation through native session callbacks", async ({ page }) => {
  await page.route("https://applepay.cdn-apple.com/**", route => route.fulfill({ contentType: "application/javascript", body: "/* Native Apple Pay SDK mocked for Chromium contract testing. */" }));
  await page.route("**/wallet-harness", route => route.fulfill({ contentType: "text/html", body: '<html><body><div id="wallet"></div></body></html>' }));
  await page.goto("/wallet-harness");
  await page.evaluate(async () => {
    const { walletFactories } = await import(/* @vite-ignore */ "/src/paypal/paypalWallets.ts");
    const events: string[] = []; Object.assign(window, { walletEvents: events });
    Object.assign(window, { ApplePaySession: class {
      static canMakePayments() { return true; } static STATUS_SUCCESS = 1; static STATUS_FAILURE = 0;
      onvalidatemerchant: any; onpaymentauthorized: any;
      begin() { this.onvalidatemerchant({ validationURL: "https://apple-pay-gateway.apple.com/paymentservices/startSession" }); }
      completeMerchantValidation() { events.push("validated"); this.onpaymentauthorized({ payment: { token: {}, billingContact: {} } }); }
      completePayment(result: any) { if (result.status !== 1) throw new Error("Unexpected failure"); events.push("completed"); }
      abort() { events.push("abort"); }
    } });
    const wallet = walletFactories({ createApplePayOneTimePaymentSession: () => ({
      formatConfigForPaymentRequest: () => ({ merchantCountry: "FR", supportedNetworks: ["visa"], merchantCapabilities: ["supports3DS"] }),
      validateMerchant: async () => { events.push("validate"); return { merchantSession: {} }; },
      confirmOrder: async () => { events.push("confirm"); return { approveApplePayPayment: { status: "APPROVED", id: "MOCK-APPLE" } }; },
    }) }, { isEligible: () => true, getDetails: () => ({ config: {} }) }).Applepay({
      amount: "5.00", currencyCode: "EUR", createOrder: async () => { events.push("create"); return "MOCK-APPLE"; }, onApprove: async () => { events.push("server-approve"); },
    });
    await wallet.render(document.querySelector<HTMLElement>("#wallet")!);
  });
  await page.locator("apple-pay-button").evaluate(element => { Object.assign((element as HTMLElement).style, { display: "block", width: "180px", height: "40px" }); });
  await page.locator("apple-pay-button").click();
  await expect.poll(() => page.evaluate(() => (window as any).walletEvents)).toEqual(["validate", "validated", "create", "confirm", "server-approve", "completed"]);
});

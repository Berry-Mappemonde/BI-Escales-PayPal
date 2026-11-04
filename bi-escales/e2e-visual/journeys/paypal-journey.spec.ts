import { expect, test, type Page } from "@playwright/test";
import {
  ADMIN_KEY,
  attachBrowserWatch,
  resetDemoLedger,
  snap,
  writeJourneyReport,
} from "../helpers/visual.js";

const J = "02-paypal-journey";

type Pledge = {
  id: string;
  status: string;
  description: string;
  authorization_id?: string | null;
  paypal_status?: string | null;
};

test.beforeEach(async ({ request }) => {
  await resetDemoLedger(request);
});

async function browserJson(
  page: Page,
  path: string,
  init: { method?: string; headers?: Record<string, string>; body?: string },
) {
  return page.evaluate(
    async ({ path, init }) => {
      const response = await fetch(path, init);
      const text = await response.text();
      let body: unknown = text;
      try {
        body = JSON.parse(text);
      } catch {
        /* keep text */
      }
      return { status: response.status, body };
    },
    { path, init },
  );
}

async function fillPledge(page: Page, description: string, milestoneId: string) {
  const form = page.locator(".pledge-form");
  await form.locator("input").nth(0).fill("20.00");
  await form.locator("input").nth(1).fill(description);
  await form.locator("input").nth(2).fill(milestoneId);
}

async function listPledges(page: Page): Promise<Pledge[]> {
  const result = await browserJson(page, "/api/escales/pledges", {
    headers: { "x-admin-key": ADMIN_KEY },
  });
  expect(result.status).toBe(200);
  return result.body as Pledge[];
}

async function postWebhook(page: Page, eventId: string, eventType: string, authorizationId: string) {
  const result = await browserJson(page, "/api/escales/webhooks/paypal", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "PAYPAL-TRANSMISSION-ID": `TX-${eventId}`,
      "PAYPAL-TRANSMISSION-TIME": "2026-11-04T12:00:00Z",
      "PAYPAL-TRANSMISSION-SIG": "demo-sig",
      "PAYPAL-CERT-URL": "https://api.sandbox.paypal.com/v1/notifications/certs/CERT",
      "PAYPAL-AUTH-ALGO": "SHA256withRSA",
    },
    body: JSON.stringify({
      id: eventId,
      event_type: eventType,
      resource: {
        id: `RES-${eventId}`,
        supplementary_data: { related_ids: { authorization_id: authorizationId } },
      },
    }),
  });
  expect(result.status, JSON.stringify(result.body)).toBe(200);
}

function queueRow(page: Page, description: string) {
  return page.locator(".treasurer-queue tbody tr").filter({ hasText: description });
}

test("authorize, vault, capture, void, webhooks, ledger", async ({ page }) => {
  const watch = attachBrowserWatch(page);

  await page.goto("/");
  await expect(page.getByTestId("demo-mode-banner")).toContainText("demo-admin-key");
  await expect(page.getByTestId("refund-absent")).toBeVisible();
  await snap(page, J, "01-home-needs-key", watch);

  await page.getByRole("button", { name: "English" }).click();
  await page.getByTestId("admin-key-input").fill(ADMIN_KEY);
  await expect(page.getByTestId("queue-empty")).toBeVisible();
  await expect(page.getByTestId("lifecycle-empty")).toBeVisible();
  await snap(page, J, "02-empty-queue-and-ledger-ready", watch);

  const created = await browserJson(page, "/api/escales/pledges", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "PayPal-Request-Id": crypto.randomUUID(),
    },
    body: JSON.stringify({
      amount_eur: "15.00",
      description: "state-created",
      milestone_id: "dep-mayotte",
    }),
  });
  expect(created.status).toBe(200);
  await page.getByRole("button", { name: "Refresh queue" }).click();
  await expect(page.locator("[data-status='created']")).toBeVisible();
  await expect(page.getByTestId("queue-empty")).toHaveCount(0);
  await snap(page, J, "03-created-in-queue", watch);

  await fillPledge(page, "state-keep-authorized", "dep-mayotte");
  await page.getByTestId("paypal-demo-approve").click();
  await expect(page.getByTestId("pledge-status")).toHaveText("Pledge authorized");
  await page.getByRole("button", { name: "Refresh queue" }).click();
  await expect(queueRow(page, "state-keep-authorized")).toBeVisible();
  await snap(page, J, "04-authorized", watch);

  for (const description of ["state-capture", "state-void", "state-pending", "state-denied", "state-settled"]) {
    await fillPledge(page, description, "dep-mayotte");
    await page.getByTestId("paypal-demo-approve").click();
    await expect(page.getByTestId("pledge-status")).toHaveText("Pledge authorized");
  }
  await page.getByRole("button", { name: "Refresh queue" }).click();
  await snap(page, J, "05-authorize-batch", watch);

  await fillPledge(page, "state-vault-keep", "dep-long-haul");
  await page.getByTestId("paypal-demo-approve").click();
  await expect(page.getByTestId("vault-setup")).toBeVisible();
  await snap(page, J, "06-vault-setup", watch);
  await page.getByRole("button", { name: /I approved/i }).click();
  await expect(page.getByTestId("pledge-status")).toHaveText("Payment method saved");

  await fillPledge(page, "state-vault-capture", "dep-long-haul");
  await page.getByTestId("paypal-demo-approve").click();
  await expect(page.getByTestId("vault-setup")).toBeVisible();
  await page.getByRole("button", { name: /I approved/i }).click();
  await expect(page.getByTestId("pledge-status")).toHaveText("Payment method saved");
  await page.getByRole("button", { name: "Refresh queue" }).click();
  await expect(page.locator("[data-status='vaulted']").first()).toBeVisible();
  await snap(page, J, "07-vaulted", watch);

  await queueRow(page, "state-capture").getByRole("button", { name: "Capture" }).click();
  await expect(page.locator("[data-status='captured']")).toBeVisible();
  await snap(page, J, "08-captured", watch);

  await queueRow(page, "state-void").getByRole("button", { name: "Void authorization" }).click();
  await expect(page.locator("[data-status='voided']")).toBeVisible();
  await snap(page, J, "09-voided", watch);

  await queueRow(page, "state-vault-capture").getByRole("button", { name: "Capture" }).click();
  await expect(page.locator("[data-status='captured']").nth(1)).toBeVisible();
  await snap(page, J, "10-vault-captured", watch);

  const beforeHooks = await listPledges(page);
  const byDescription = (description: string) => {
    const pledge = beforeHooks.find((item) => item.description === description);
    expect(pledge?.authorization_id, description).toBeTruthy();
    return pledge as Pledge;
  };
  await postWebhook(page, "EVT-PENDING", "PAYMENT.CAPTURE.PENDING", byDescription("state-pending").authorization_id as string);
  await postWebhook(page, "EVT-DENIED", "PAYMENT.CAPTURE.DENIED", byDescription("state-denied").authorization_id as string);
  await postWebhook(
    page,
    "EVT-SETTLED",
    "PAYMENT.CAPTURE.COMPLETED",
    byDescription("state-settled").authorization_id as string,
  );
  await page.getByRole("button", { name: "Refresh queue" }).click();
  await expect(page.locator("[data-status='pending']")).toBeVisible();
  await expect(page.locator("[data-status='failed']")).toHaveAttribute("data-paypal-status", "DENIED");
  await expect(page.locator("[data-status='settled']")).toBeVisible();
  await expect(page.locator("[data-status='authorized']")).toBeVisible();
  await expect(page.locator("[data-status='vaulted']")).toBeVisible();
  await expect(page.locator("[data-status='refunded']")).toHaveCount(0);
  await snap(page, J, "11-webhooks-pending-denied-settled", watch);

  await postWebhook(
    page,
    "EVT-REFUNDED",
    "PAYMENT.CAPTURE.REFUNDED",
    byDescription("state-settled").authorization_id as string,
  );
  await page.getByRole("button", { name: "Refresh queue" }).click();
  await expect(page.locator("[data-status='refunded']")).toBeVisible();
  await snap(page, J, "12-refunded", watch);

  await queueRow(page, "state-pending").getByRole("button", { name: "Void authorization" }).click();
  await expect(page.locator("[data-status='voided']").filter({ hasText: "state-pending" })).toBeVisible();
  await snap(page, J, "13-pending-voided", watch);

  await page.evaluate(() => localStorage.clear());
  await page.getByRole("button", { name: "Refresh queue" }).click();
  await expect(page.locator("[data-status='created']")).toBeVisible();
  await snap(page, J, "14-queue-survives-without-localstorage", watch);

  await page.getByRole("button", { name: "Load ledger" }).click();
  await expect(page.locator(".finance-ledger tbody tr").filter({ hasText: "webhook_received" }).first()).toBeVisible();
  await expect(page.locator(".finance-ledger")).toContainText("pledge_captured");
  await snap(page, J, "15-finance-ledger", watch);

  const a11y = await watch.collectA11y(page);
  writeJourneyReport(J, watch, a11y);
});

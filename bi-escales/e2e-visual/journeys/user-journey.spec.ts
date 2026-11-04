import { expect, test } from "@playwright/test";
import {
  ADMIN_KEY,
  attachBrowserWatch,
  resetDemoLedger,
  snap,
  writeJourneyReport,
} from "../helpers/visual.js";

const J = "01-user-journey";

test.beforeEach(async ({ request }) => {
  await resetDemoLedger(request);
});

test("supporter, captain, treasurer, ledger", async ({ page }) => {
  const watch = attachBrowserWatch(page);

  await page.goto("/");
  await expect(page.getByTestId("demo-mode-banner")).toBeVisible();
  await expect(page.getByTestId("health-status")).toHaveText(/disponible/i);
  await expect(page.getByText("2027-05-15")).toBeVisible();
  await expect(page.getByText("2026-09-01")).toHaveCount(0);
  await snap(page, J, "01-home-fr", watch);

  await page.getByRole("button", { name: "English" }).click();
  await expect(page.getByTestId("health-status")).toHaveText("Backend reachable");
  await expect(page.getByText("2027-05-15")).toBeVisible();
  await snap(page, J, "02-language-en", watch);
  const a11yEarly = await watch.collectA11y(page);

  await page.getByRole("button", { name: "Refresh milestones" }).click();
  await expect(page.locator(".milestone-list li").first()).toBeVisible();
  await snap(page, J, "03-milestones", watch);

  await page.getByRole("button", { name: "Record evidence" }).click();
  await expect(page.locator(".milestone-list")).toContainText("dep-mayotte");
  await snap(page, J, "04-evidence", watch);

  await page.getByRole("button", { name: "Ask for wording" }).click();
  await expect(page.getByTestId("chat-model-source")).toBeVisible();
  await snap(page, J, "05-captain-chat", watch);

  await expect(page.getByTestId("queue-needs-key")).toBeVisible();
  await expect(page.getByTestId("lifecycle-needs-key")).toBeVisible();
  await snap(page, J, "06-queue-needs-key", watch);

  await page.getByTestId("admin-key-input").fill("wrong-key");
  await expect(page.getByTestId("queue-error")).toBeVisible();
  await snap(page, J, "07-wrong-admin-key", watch);

  await page.route(
    "**/api/escales/pledges",
    async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 800));
      await route.fallback();
    },
    { times: 1 },
  );
  await page.getByTestId("admin-key-input").fill(ADMIN_KEY);
  await expect(page.getByTestId("queue-loading")).toBeVisible();
  await snap(page, J, "08-queue-loading", watch);
  await expect(page.getByTestId("queue-empty")).toBeVisible();
  await page.unrouteAll({ behavior: "ignoreErrors" });
  await snap(page, J, "09-queue-empty", watch);

  await page.getByRole("button", { name: "Request captain review" }).click();
  await expect(page.getByTestId("captain-model-source")).toBeVisible();
  await snap(page, J, "10-captain-review", watch);

  await expect(page.locator(".pledge-form input").nth(2)).toHaveValue("dep-mayotte");
  await page.getByTestId("paypal-demo-approve").click();
  await expect(page.getByTestId("pledge-status")).toHaveText("Pledge authorized");
  await snap(page, J, "12-pledge-authorized", watch);

  await page.getByRole("button", { name: "Refresh queue" }).click();
  await expect(page.locator(".treasurer-queue tbody tr").first()).toBeVisible();
  await expect(page.locator("[data-status='authorized']")).toBeVisible();
  await snap(page, J, "13-queue-with-pledge", watch);

  await page.locator(".treasurer-queue").getByRole("button", { name: "Capture" }).click();
  await expect(page.locator("[data-status='captured']")).toBeVisible();
  await snap(page, J, "14-after-capture", watch);

  await page.getByRole("button", { name: "Load ledger" }).click();
  await expect(page.locator(".finance-ledger tbody tr").first()).toBeVisible();
  await snap(page, J, "15-finance-ledger", watch);

  const a11yLate = await watch.collectA11y(page);
  const seen = new Set<string>();
  const a11y = [...a11yEarly, ...a11yLate].filter((issue) => {
    const key = `${issue.message}|${issue.sourceFile}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
  writeJourneyReport(J, watch, a11y);
});

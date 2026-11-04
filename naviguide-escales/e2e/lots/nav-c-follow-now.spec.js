// Follow: Now, Journal, Story and moment cards use the clock, not the cursor.
import { expect, test } from "@playwright/test";

const T0 = "2026-05-15T08:00:00Z";
const JOURNAL_DAYS = ["2026-05-15", "2026-05-16", "2026-05-17", "2026-06-01", "2026-10-17"];

function json(route, body, status = 200) {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

function clockFromMarks(marks) {
  const list = Array.isArray(marks) ? marks.filter((m) => m && m.name) : [];
  if (list.length < 2) return null;
  let index = list.findIndex((m) => /Nouméa|Mata-Utu|Wallis|Papeete|Tahiti/i.test(m.name));
  if (index < 0 || index >= list.length - 1) {
    index = Math.max(0, Math.min(list.length - 2, Math.floor(list.length * 0.72)));
  }
  const from = list[index];
  const to = list[index + 1];
  const t0ms = Date.parse(T0);
  const nowHours = (Date.now() - t0ms) / 3600000;
  const clockMarks = list.map((m, i) => {
    const hours = i <= index
      ? nowHours * (i / Math.max(1, index)) * 0.98
      : nowHours + (i - index) * 72;
    return {
      ...m,
      iso: new Date(t0ms + hours * 3600000).toISOString(),
      holdHours: i === index ? 0 : 0,
    };
  });
  const vertex = (hours, mark, knots) => ({
    tHours: hours,
    sailNm: Number(mark.nm) || 0,
    filmNm: Number(mark.filmNm ?? mark.nm) || 0,
    lat: mark.lat,
    lon: mark.lon,
    speedKnots: knots,
    bearing: 210,
    vehicle: "main",
    kind: "climatology",
  });
  return {
    fromName: from.name,
    toName: to.name,
    from,
    clock: {
      t0: T0,
      marks: clockMarks,
      vertices: [
        vertex(0, list[0], 6),
        vertex(Math.max(1, nowHours - 24), from, 7.5),
        vertex(nowHours + 400, to, 7.5),
      ],
    },
  };
}

async function dismissNotForNav(page) {
  const ok = page.getByRole("button", { name: /compris|j.ai compris|ok|continuer|accepter|understand|accept/i }).first();
  if (await ok.isVisible({ timeout: 3000 }).catch(() => false)) {
    const ack = page.getByTestId("not-for-nav-ack");
    if (await ack.isVisible().catch(() => false)) await ack.check();
    await ok.click();
  }
}

async function leaveCinema(page) {
  const cinema = page.getByRole("button", { name: /^(cinéma|cinema)$/i });
  if (!(await cinema.isVisible().catch(() => false))) return;
  const on = /bg-cyan-700/.test((await cinema.getAttribute("class")) || "");
  if (on) await cinema.click();
}

async function showLeftPanel(page) {
  await leaveCinema(page);
  const box = page.getByTestId("ici-maintenant");
  if (await box.isVisible({ timeout: 2_000 }).catch(() => false)) return;
  await page.locator(".naviguide-sidebar-toggle--left").click();
  await expect(box).toBeVisible({ timeout: 15_000 });
}

test("NAV-C follow now, journal, story and moment cards", async ({ page }) => {
  test.setTimeout(90_000);
  let built = null;
  const errors = [];
  page.on("pageerror", (err) => errors.push(String(err)));

  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const api = path.includes("/voyage") || path.includes("/ici");
    if (!api) return route.continue();
    if (path.includes("/ici/moment")) {
      return json(route, {
        signature: "stale-leg",
        t: "2026-05-17T12:00:00Z",
        leg: { from: "La Rochelle", to: "Ajaccio (Corse)", day: 2, kn: 5.1, remainingNm: 1453 },
        alerts: [],
        here: { sentences: ["Le bateau est en mer."] },
        around: [{ kind: "port", title: "Porto de Malpica", fact: "23 nm", url: "https://example.test/around" }],
        sources: ["clock"],
      });
    }
    const day = path.match(/\/voyage\/official\/journal\/(\d{4}-\d{2}-\d{2})$/);
    if (day) {
      const name = day[1];
      return json(route, {
        voyageId: "official",
        day: name,
        status: "ready",
        entries: [{
          id: `e-${name}`,
          t: `${name}T12:00:00Z`,
          kind: "position",
          lat: name === "2026-05-17" ? 43.37 : 46.16,
          lon: name === "2026-05-17" ? -8.41 : -1.15,
          name: name === "2026-05-17" ? "La Coruna" : name,
        }],
      });
    }
    if (path.endsWith("/voyage/official/journal")) {
      return json(route, {
        voyageId: "official",
        status: "ready",
        count: JOURNAL_DAYS.length * 4,
        first: JOURNAL_DAYS[0],
        last: JOURNAL_DAYS[JOURNAL_DAYS.length - 1],
        days: JOURNAL_DAYS.map((d) => ({ day: d, count: 4 })),
        latest: [],
        events: [],
      });
    }
    if (path.includes("/voyage/official/moments")) {
      const lat = built?.from?.lat ?? -22.2;
      const lon = built?.from?.lon ?? 166.4;
      return json(route, {
        voyageId: "official",
        status: "ready",
        count: 2,
        moments: [
          {
            t: "2026-05-17T12:00:00Z",
            signature: "early",
            pos: { lat: 43.3, lon: -8.4 },
            leg: { from: "La Rochelle", to: "Ajaccio (Corse)", day: 2, kn: 5.1, remainingNm: 1453 },
            alerts: [],
            around: [],
          },
          {
            t: "2026-10-18T00:00:00Z",
            signature: "live",
            pos: { lat, lon },
            alerts: [{ id: "now", title: "Carte maintenant", fact: "au bateau", severity: "alert" }],
            around: [
              { kind: "marina", title: "Marina de Nouméa", fact: "à portée", url: "https://example.test/marina", lat, lon },
              { kind: "poe", title: "Port d'entrée", fact: "formel", url: "https://example.test/poe", lat: lat + 0.2, lon },
            ],
          },
        ],
      });
    }
    if (path.includes("/voyage/official/grib")) return json(route, { status: "absent" });
    if (path.includes("/voyage/official/film")) return json(route, { status: "ready", chapters: [] });
    if (path.endsWith("/voyage/official/clock")) {
      if (!built?.clock) return json(route, { detail: "clock" }, 404);
      return json(route, built.clock);
    }
    if (path.endsWith("/voyage/official")) {
      if (route.request().method() === "PUT") {
        let body = {};
        try { body = route.request().postDataJSON(); } catch { body = {}; }
        built = clockFromMarks(body.marks) || built;
      }
      return json(route, { voyageId: "official", status: "ready", clock: built?.clock || null });
    }
    return json(route, { status: "ready" });
  });

  await page.goto("/");
  await dismissNotForNav(page);
  await showLeftPanel(page);

  const leg = page.getByTestId("ici-leg-line");
  await expect(leg).toBeVisible({ timeout: 20_000 });
  await expect.poll(async () => {
    const text = ((await leg.innerText()) || "").replace(/\s+/g, " ");
    return built?.toName && text.includes(built.toName) ? text : "";
  }, { timeout: 25_000 }).not.toEqual("");
  const legText = ((await leg.innerText()) || "").replace(/\s+/g, " ");
  expect(legText).toContain(built.fromName);
  expect(legText).toContain(built.toName);
  expect(legText).not.toMatch(/La Rochelle\s*→\s*Ajaccio/);

  const around = page.getByTestId("ici-around-link");
  await expect(around.first()).toHaveAttribute("href", "https://example.test/around");

  const nowCard = page.getByTestId("moment-now");
  const freeCard = page.getByTestId("moment-free");
  await expect(nowCard).toContainText("Carte maintenant");
  await expect(freeCard).toContainText("Marina de Nouméa");
  await expect(freeCard.getByTestId("moment-link-site")).toHaveAttribute("href", "https://example.test/marina");
  await expect(freeCard.getByTestId("moment-link-maps")).toHaveAttribute("href", /google\.com\/maps/);
  const clickCard = (locator) => locator.evaluate((el) => el.click());
  await clickCard(freeCard.getByTestId("moment-focus"));
  await clickCard(freeCard.getByTestId("moment-next"));
  await expect(freeCard).toContainText("Port d'entrée");
  await clickCard(nowCard.getByTestId("moment-dismiss"));
  await expect(nowCard).toHaveCount(0);

  await clickCard(page.getByTestId("ici-tab-story"));
  await expect(page.getByTestId("expedition-story")).toBeVisible();
  await expect(page.getByTestId("story-paragraph").first()).toBeVisible();
  await expect(page.getByTestId("moment-free")).toContainText("Port d'entrée");

  await clickCard(page.getByTestId("ici-tab-journal"));
  const days = page.getByTestId("journal-day");
  await expect(days).toHaveCount(JOURNAL_DAYS.length);
  await expect(days.first()).toHaveAttribute("data-day", "2026-05-15");
  await clickCard(page.locator('[data-testid="journal-day"][data-day="2026-05-17"]'));
  await expect(page.getByTestId("ici-journal-entry")).toContainText("La Coruna");
  await clickCard(page.getByTestId("ici-tab-now"));
  const legAfter = ((await page.getByTestId("ici-leg-line").innerText()) || "").replace(/\s+/g, " ");
  expect(legAfter).toContain(built.toName);
  expect(legAfter).not.toMatch(/La Rochelle\s*→\s*Ajaccio/);

  expect(errors, errors.join("\n")).toEqual([]);
});

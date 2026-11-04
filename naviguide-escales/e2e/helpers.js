// Contrats UI actuels (RF7, RD9, RE3, RF8, RC18) — partagés par les scénarios.
import { expect } from "@playwright/test";

// The "not for navigation" modal only opens after a gated action, never on load,
// so by default this checks once without waiting, as the per-spec copies did.
// A fixed wait would run in full before every spec and shift the timing they
// rely on. Pass `timeout` (ms) right after an action that opens the modal.
export async function dismissNotForNav(page, { timeout = 0 } = {}) {
  const modal = page.getByTestId("not-for-nav-modal");
  const visible = timeout > 0
    ? await modal.waitFor({ state: "visible", timeout }).then(() => true).catch(() => false)
    : await modal.isVisible().catch(() => false);
  if (!visible) return;
  const ack = modal.getByTestId("not-for-nav-ack");
  if (await ack.isVisible().catch(() => false)) await ack.check();
  const ok = modal.getByTestId("not-for-nav-accept");
  if (await ok.isVisible().catch(() => false)) {
    await ok.click();
    return;
  }
  const modalOk = modal.getByRole("button", {
    name: /compris|j.ai compris|ok|continuer|accepter|understand|accept/i,
  }).first();
  if (await modalOk.isVisible().catch(() => false)) await modalOk.click();
}

// Same contract as dismissNotForNav: one check by default, a real wait with `timeout` (ms).
export async function dismissAiChatNotice(page, { timeout = 0 } = {}) {
  const notice = page.getByTestId("logbook-chat-ai-notice");
  const visible = timeout > 0
    ? await notice.waitFor({ state: "visible", timeout }).then(() => true).catch(() => false)
    : await notice.isVisible().catch(() => false);
  if (!visible) return;
  const btn = notice.getByTestId("logbook-chat-ai-notice-dismiss");
  if (await btn.isVisible().catch(() => false)) await btn.click();
}

export function cinemaButton(page) {
  return page.getByRole("button", { name: /^(cinéma|cinema)$/i });
}

export async function cinemaPressed(page) {
  return /bg-cyan-700/.test((await cinemaButton(page).getAttribute("class")) || "");
}

export async function leaveCinema(page) {
  const cinema = cinemaButton(page);
  if (!(await cinema.isVisible().catch(() => false))) return;
  if (!(await cinemaPressed(page))) return;
  await page.keyboard.press("Escape");
  if (!(await cinemaPressed(page))) return;
  await cinema.evaluate((el) => el.click());
}

export async function panelClosed(page, side) {
  const loc = side === "left"
    ? page.locator(".naviguide-sidebar-panel.left-0").first()
    : page.locator(".naviguide-sidebar-panel.right-0").first();
  const cls = (await loc.getAttribute("class")) || "";
  return cls.includes("translate-x-full");
}

// The drawer's buttons stay visibility:hidden until it has slid in (5dbab1a), and its box
// counts as visible even while slid off-screen. So read the toggle, never a button or the
// box: clicking the toggle on a drawer that is already opening closes it.
export async function openLeftDrawer(page) {
  const toggle = page.locator(".naviguide-sidebar-toggle--left");
  if ((await toggle.getAttribute("aria-expanded")) !== "true") await toggle.click();
  const drawer = page.locator(".naviguide-sidebar-drawer");
  await expect(drawer).toHaveClass(/naviguide-drawer-settled/, { timeout: 15_000 });
  await expect(drawer).toBeInViewport();
}

export async function showLeftPanel(page) {
  await leaveCinema(page);
  const box = page.getByTestId("ici-maintenant");
  if (await box.isVisible().catch(() => false)) return;
  const toggle = page.locator(".naviguide-sidebar-toggle--left");
  if (await toggle.isVisible().catch(() => false)) await toggle.evaluate((el) => el.click());
  await expect(box).toBeVisible({ timeout: 15_000 });
}

export async function showRightPanel(page) {
  await leaveCinema(page);
  if (!(await panelClosed(page, "right").catch(() => true))) {
    await bringOffscreenFlagsIntoView(page);
    return;
  }
  const toggle = page.locator(".naviguide-sidebar-toggle--right");
  if (await toggle.isVisible().catch(() => false)) await toggle.evaluate((el) => el.click());
  await expect.poll(() => panelClosed(page, "right"), { timeout: 10_000 }).toBe(false);
  await bringOffscreenFlagsIntoView(page);
}

/** Drapeaux Leaflet hors cadre : le scroll de page ne les ramène pas. */
export async function bringOffscreenFlagsIntoView(page) {
  await page.evaluate(() => {
    const scene = window.__naviguideScene;
    const map = scene?.map;
    if (!map || !scene.waypointMarkers?.size) return;
    const box = map.getContainer().getBoundingClientRect();
    const off = [];
    for (const marker of scene.waypointMarkers.values()) {
      const el = marker.getElement?.() || marker._icon;
      const r = el?.getBoundingClientRect?.();
      const ll = marker.getLatLng?.();
      if (!ll) continue;
      if (!r || r.width === 0 || r.right < box.left || r.left > box.right || r.bottom < box.top || r.top > box.bottom) {
        off.push([ll.lat, ll.lng]);
      }
    }
    if (!off.length) return;
    map.fitBounds(off, { padding: [48, 48], maxZoom: 7, animate: false });
  });
}

export async function openIciTab(page, testId, slotTestId) {
  await showLeftPanel(page);
  const tab = page.getByTestId(testId);
  await expect(tab).toBeVisible({ timeout: 10_000 });
  await tab.evaluate((el) => el.click());
  if (slotTestId) {
    await expect(tab).toHaveAttribute("aria-selected", "true");
    await expect(page.getByTestId(slotTestId)).toBeAttached({ timeout: 10_000 });
  }
}

export async function openReviewTab(page) {
  await openIciTab(page, "ici-tab-review", "ici-review-slot");
  await expect(page.getByTestId("plan-review")).toBeVisible({ timeout: 10_000 });
  await ensureReviewOpen(page);
}

/**
 * GET /plan-review peut être `preparing` (nouvelle clé PLAN_REVIEW_REV).
 * Les assertions sur les jambes ne tiennent que si le GET est `ready`.
 */
export async function probeOfficialPlanReview(page) {
  const official = await page.request.get("/voyage/official", { timeout: 5000 }).catch(() => null);
  const apiUp = Boolean(official && official.ok());
  if (!apiUp) return { apiUp: false, reviewReady: false, legs: [], body: null };
  const body = await page.request.get("/voyage/official/plan-review", { timeout: 8000 })
    .then((r) => (r.ok() ? r.json() : null))
    .catch(() => null);
  const legs = Array.isArray(body?.legs) ? body.legs : [];
  const reviewReady = body?.status === "ready" && legs.length > 0;
  return { apiUp, reviewReady, legs, body };
}

/** Dans l'onglet, PlanReview est un `div` (startOpen), plus un `<details>`. */
export async function ensureReviewOpen(page) {
  const review = page.getByTestId("plan-review");
  await expect(review).toBeVisible({ timeout: 10_000 });
  const summary = review.locator("summary");
  if ((await summary.count()) === 0) return;
  const isOpen = await review.evaluate((el) => el.tagName.toLowerCase() !== "details" || el.open);
  if (!isOpen) await summary.click();
}

export async function openStoryTab(page) {
  await openIciTab(page, "ici-tab-story", "ici-story-slot");
}

export async function openJournalTab(page) {
  await openIciTab(page, "ici-tab-journal", "ici-journal-slot");
}

/** Clique la pilule Tracer (la vue), sans ouvrir le dessin. */
export async function enterTracerView(page) {
  await page.getByTestId("view-tracer").click();
  await expect(page.getByTestId("view-tracer")).toHaveAttribute("aria-checked", "true");
}

/** @deprecated alias à retirer — même geste que enterTracerView.
 *  Ne pas confondre avec enterTracer, qui ouvre aussi le dessin. */
export const enterSimulation = enterTracerView;

export const enterTracerMode = enterTracerView;

export async function enterTracer(page) {
  // Entrer en Tracer ouvre le dessin (brouillon vide ou déjà là).
  // Le cadre droit (drawing-box) n'apparaît qu'après « Tracer votre propre
  // route » : drawing-points à gauche ne suffit pas (RH2).
  await showLeftPanel(page);
  const tracer = page.getByTestId("view-tracer");
  if ((await tracer.getAttribute("aria-checked")) !== "true") {
    await tracer.click();
  }
  await expect(tracer).toHaveAttribute("aria-checked", "true");
  const box = page.getByTestId("drawing-box");
  if (!(await box.isVisible().catch(() => false))) {
    const drawBtn = page.getByRole("button", {
      name: /Berry-Mappemonde.*Tracer votre propre route|Tracer votre propre route|Draw your own route/i,
    });
    await expect(drawBtn).toBeVisible({ timeout: 10_000 });
    await drawBtn.scrollIntoViewIfNeeded();
    // Sous charge (tranches CI), le bouton peut être hors du cadre de la fenêtre au moment du clic
    // (panneau en transition) : le clic DOM ne dépend pas de la géométrie.
    await drawBtn.click({ force: true, timeout: 5_000 }).catch(() => drawBtn.evaluate((el) => el.click()));
  }
  if (!(await box.isVisible().catch(() => false))) {
    await showRightPanel(page);
  }
  await expect(box).toBeVisible({ timeout: 15_000 });
  await page.evaluate(() => window.__naviguideScene?.beginDrawingWorld?.());
}

export async function probeOfficial(requestOrPage) {
  const req = requestOrPage.request || requestOrPage;
  const official = await req.get("/voyage/official", { timeout: 5000 }).catch(() => null);
  if (!official || !official.ok()) return null;
  const ct = official.headers()["content-type"] || "";
  if (!ct.includes("json")) return null;
  const body = await official.json().catch(() => null);
  return body && typeof body === "object" ? body : null;
}

export async function mapZoom(page) {
  return page.evaluate(() => window.__naviguideScene?.map?.getZoom?.() ?? null);
}

/** Plancher RC18 sur le viewport Playwright 1280×800 : 2.5. */
export const FOLLOW_ZOOM_FLOOR = 2.5;

/** Cadrage Suivre : zoom plancher + distance pixel bateau → centre. */
export async function mapFollowCadrage(page) {
  return page.evaluate(() => {
    const scene = window.__naviguideScene;
    const map = scene?.map;
    if (!map) return null;
    const center = map.getCenter();
    const live = scene.config?.live;
    const marker = scene.mainBoatMarker?.()?.getLatLng?.();
    const lat = Number(marker?.lat ?? live?.lat);
    const lng = Number(marker?.lng ?? live?.lon);
    const boat = Number.isFinite(lat) && Number.isFinite(lng) ? { lat, lon: lng } : null;
    let boatPx = null;
    if (boat) {
      const c = map.latLngToContainerPoint(center);
      const b = map.latLngToContainerPoint([boat.lat, boat.lon]);
      boatPx = Math.hypot(b.x - c.x, b.y - c.y);
    }
    const box = map.getContainer().getBoundingClientRect();
    const cx = box.left + box.width / 2;
    const cy = box.top + box.height / 2;
    let iconPx = null;
    for (const el of document.querySelectorAll(".catamaran-divicon--live, .catamaran-divicon")) {
      const r = el.getBoundingClientRect();
      if (!r.width || !r.height) continue;
      const d = Math.hypot(r.left + r.width / 2 - cx, r.top + r.height / 2 - cy);
      if (iconPx == null || d < iconPx) iconPx = d;
    }
    const px = Number.isFinite(boatPx) ? boatPx : iconPx;
    return {
      zoom: map.getZoom(),
      minZoom: map.getMinZoom(),
      cx: center.lat,
      cy: center.lng,
      boat,
      boatPx: Number.isFinite(px) ? px : boatPx,
      iconPx,
    };
  });
}

export async function waitFilmCanStart(page, timeout = 25_000) {
  const start = page.getByTestId("replay-start");
  await expect(start).toBeVisible({ timeout: 15_000 });
  await page.waitForFunction(() => {
    const b = document.querySelector("[data-testid='replay-start']");
    return Boolean(b && !b.disabled && b.getAttribute("aria-disabled") !== "true");
  }, null, { timeout }).catch(() => null);
  return start.isEnabled();
}

/**
 * Le film officiel est prêt — télémétrie `window.__naviguideFilm.status`
 * (si le client la publie) ou bouton Revoir actif (`remoteStatus === "ready"`).
 * Ne pas avaler le timeout : si l'API est là, un échec est une régression.
 */
export async function waitFilmReady(page, timeout = 45_000) {
  const start = page.getByTestId("replay-start");
  await expect(start).toBeVisible({ timeout: 15_000 });
  await page.waitForFunction(() => {
    const st = window.__naviguideFilm?.status;
    const b = document.querySelector("[data-testid='replay-start']");
    const enabled = Boolean(b && !b.disabled && b.getAttribute("aria-disabled") !== "true");
    return st === "ready" || enabled;
  }, null, { timeout });
  await expect(start).toBeEnabled();
}

/**
 * Le film ancré (RC18) laisse le bateau à quai pendant les premières phrases (Saint-Maur → La Rochelle
 * par la route — comptée dans filmNm —, puis l'escale) : on ne mesure sa glisse qu'une fois qu'il BOUGE
 * vraiment, après le premier quai (un premier épisode de route, un palier, puis la mer). Un seul saut
 * d'arrivée à quai n'est pas « en route » : la glisse y recule ou s'arrête.
 */
export async function waitBoatUnderWay(page, { minDeg = 0.01, timeout = 60_000, stableMs = 1_500 } = {}) {
  return page.evaluate(async ([min, limit, hold]) => {
    const read = () => {
      const f = window.__naviguideFilm || {};
      return Number.isFinite(f.lat) && Number.isFinite(f.lon) ? { lat: f.lat, lon: f.lon, nm: Number(f.filmNm) || 0, ended: Boolean(f.ended) } : null;
    };
    const twitch = min * 0.05;
    const t0 = performance.now();
    let prev = read();
    let seenMove = false;
    let afterQuay = false;
    let quietMs = 0;
    let seaMs = 0;
    let lastTick = t0;
    while (performance.now() - t0 < limit) {
      await new Promise((r) => setTimeout(r, 400));
      const now = performance.now();
      const dt = now - lastTick;
      lastTick = now;
      const cur = read();
      if (cur?.ended) return { moving: false, ended: true, nm: cur.nm };
      const dist = prev && cur
        ? Math.abs(cur.lat - prev.lat) + Math.abs(cur.lon - prev.lon)
        : 0;
      prev = cur || prev;
      if (dist > twitch) {
        seenMove = true;
        quietMs = 0;
        if (afterQuay) {
          seaMs += dt;
          if (seaMs >= hold) return { moving: true, ended: false, nm: cur?.nm || 0 };
        }
      } else {
        seaMs = 0;
        if (seenMove) {
          quietMs += dt;
          if (quietMs >= 800) afterQuay = true;
        }
      }
    }
    return { moving: false, ended: false, nm: prev?.nm || 0 };
  }, [minDeg, timeout, stableMs]);
}

/** Le récit du panneau gauche dans la langue demandée (après une bascule FR/EN, il se recharge). */
export async function waitStoryLang(page, lang, timeout = 20_000) {
  const re = lang === "en" ? /expedition|left|departure|arrival/i : /expédition|quitté|départ|arrivée/i;
  await page.waitForFunction(([pattern, flags]) => {
    const box = document.querySelector("[data-testid='expedition-story']");
    const txt = box ? box.textContent || "" : "";
    const names = ["Saint-Maur", "La Rochelle", "Ajaccio", "Fort-de-France"].filter((n) => txt.includes(n));
    return new RegExp(pattern, flags).test(txt) && names.length >= 3;
  }, [re.source, re.flags], { timeout }).catch(() => null);
}

/** Recentre la carte sur le drapeau d'une escale : en Suivre la caméra LIVE
 *  (Pacifique) et le cadrage pending ramènent le bateau — sans lâcher
 *  le suivi, setView ne tient pas et un clic « force » n'atteint rien. */
export async function centerOnFlag(page, namePattern, zoom = 7) {
  const source = namePattern instanceof RegExp ? namePattern.source : String(namePattern);
  return page.evaluate(([src, z]) => {
    const scene = window.__naviguideScene;
    if (!scene?.map || !scene.waypointMarkers) return false;
    scene._pendingFollowCadrage = false;
    scene.userNavigated = true;
    try { scene.callbacks?.onManualNavigation?.(); } catch { /* tests */ }
    const re = new RegExp(src, "i");
    for (const marker of scene.waypointMarkers.values()) {
      if (re.test(marker._naviguideWaypoint?.name || "")) {
        scene.map.setView(marker.getLatLng(), z, { animate: false });
        return true;
      }
    }
    return false;
  }, [source, zoom]).then(async (ok) => {
    await page.waitForTimeout(300);
    return Boolean(ok);
  });
}

// Leaflet dessine le monde sur plusieurs copies côte à côte : le marqueur « principal » est celui de la
// copie la plus proche de la caméra. Deux lectures du même point peuvent donc différer de 360°
// (210,43 et −149,57 : le bateau n'a pas bougé). Comparer des longitudes brutes donne un faux « saut ».
export function wrapLng(lng) {
  return ((((lng + 180) % 360) + 360) % 360) - 180;
}

export function lngDelta(a, b) {
  const x = ((((b - a) % 360) + 360) % 360);
  return Math.min(x, 360 - x);
}

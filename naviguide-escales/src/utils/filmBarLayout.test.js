import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  ATTRIBUTION_FILM_GAP_PX,
  FILM_BAR_BOTTOM_GAP_PX,
  FILM_BAR_HEIGHT_PX,
  NARROW_LAYOUT_MAX_PX,
  SIDEBAR_WIDTH_PX,
  drawerFilmBarInsets,
  filmBarEdgeStyle,
  filmBarInsets,
  isNarrowLayout,
  mapInsetVars,
  measureFilmBarOccupiedPx,
} from "./filmBarLayout.js";

describe("filmBarLayout U6", () => {
  it("entre les deux sidebars ouvertes", () => {
    const box = filmBarInsets({ sidebarOpen: true, toolsOpen: true });
    assert.equal(box.left, SIDEBAR_WIDTH_PX);
    assert.equal(box.right, SIDEBAR_WIDTH_PX);
  });

  it("s’élargit si une sidebar se range", () => {
    const cinema = filmBarInsets({ sidebarOpen: false, toolsOpen: false, gutter: 8 });
    assert.equal(cinema.left, 8);
    assert.equal(cinema.right, 8);
    const leftOnly = filmBarInsets({ sidebarOpen: true, toolsOpen: false, gutter: 8 });
    assert.equal(leftOnly.left, SIDEBAR_WIDTH_PX);
    assert.equal(leftOnly.right, 8);
  });
});

describe("mapInsetVars — crédits Leaflet dans la carte visible", () => {
  it("se décale du panneau Outils ; premier rendu = constantes + 4 px", () => {
    const vars = mapInsetVars({ sidebarOpen: true, toolsOpen: true, filmBarVisible: true, filmBarControls: true });
    assert.equal(vars["--sim-inset-right"], `${SIDEBAR_WIDTH_PX}px`);
    assert.equal(
      vars["--sim-inset-bottom"],
      `${FILM_BAR_HEIGHT_PX.controls + FILM_BAR_BOTTOM_GAP_PX + ATTRIBUTION_FILM_GAP_PX}px`,
    );
  });

  it("Suivre : même plancher de premier rendu ; barre invisible : rien", () => {
    const suivre = mapInsetVars({ toolsOpen: false, filmBarVisible: true, filmBarControls: false });
    assert.equal(suivre["--sim-inset-right"], "0px");
    assert.equal(
      suivre["--sim-inset-bottom"],
      `${FILM_BAR_HEIGHT_PX.compact + FILM_BAR_BOTTOM_GAP_PX + ATTRIBUTION_FILM_GAP_PX}px`,
    );
    const hidden = mapInsetVars({ toolsOpen: false, filmBarVisible: false });
    assert.equal(hidden["--sim-inset-bottom"], "0px");
  });

  it("inset = mesure + 10", () => {
    const tall = mapInsetVars({ filmBarVisible: true, filmBarMeasuredPx: 140 });
    assert.equal(tall["--sim-inset-bottom"], `${140 + ATTRIBUTION_FILM_GAP_PX}px`);
    const chip = mapInsetVars({ filmBarVisible: true, filmBarMeasuredPx: 44 });
    assert.equal(chip["--sim-inset-bottom"], `${44 + ATTRIBUTION_FILM_GAP_PX}px`);
    assert.equal(ATTRIBUTION_FILM_GAP_PX, 10);
  });

  it("mesure l’occupation depuis le bas jusqu’au haut de la barre", () => {
    const el = { getBoundingClientRect: () => ({ top: 680, bottom: 780 }) };
    assert.equal(measureFilmBarOccupiedPx(el, 800), 120);
    assert.equal(measureFilmBarOccupiedPx(null, 800), 0);
  });
});

describe("tiroir sous 600 px — la barre ne réserve plus la colonne", () => {
  it("599 px : gouttière des deux côtés, même panneaux ouverts", () => {
    assert.equal(NARROW_LAYOUT_MAX_PX, 599);
    assert.equal(isNarrowLayout(390), true);
    assert.equal(isNarrowLayout(599), true);
    assert.equal(isNarrowLayout(600), false);
    assert.equal(isNarrowLayout(1280), false);
    const phone = drawerFilmBarInsets({ sidebarOpen: true, toolsOpen: true, viewportWidth: 390 });
    assert.equal(phone.left, 8);
    assert.equal(phone.right, 8);
    const edge = drawerFilmBarInsets({ sidebarOpen: true, toolsOpen: false, viewportWidth: 599 });
    assert.equal(edge.left, 8);
    assert.equal(edge.right, 8);
  });

  it("600 px et bureau : la barre reste entre les panneaux", () => {
    const desk = drawerFilmBarInsets({ sidebarOpen: true, toolsOpen: true, viewportWidth: 600 });
    assert.equal(desk.left, SIDEBAR_WIDTH_PX);
    assert.equal(desk.right, SIDEBAR_WIDTH_PX);
    const wide = drawerFilmBarInsets({ sidebarOpen: true, toolsOpen: false, viewportWidth: 1280, gutter: 8 });
    assert.equal(wide.left, SIDEBAR_WIDTH_PX);
    assert.equal(wide.right, 8);
    const unknown = drawerFilmBarInsets({ sidebarOpen: true, toolsOpen: true });
    assert.equal(unknown.left, SIDEBAR_WIDTH_PX);
    assert.equal(unknown.right, SIDEBAR_WIDTH_PX);
  });

  it("crédits : la colonne reste réservée ; la barre, non", () => {
    const phone = mapInsetVars({
      sidebarOpen: true,
      toolsOpen: true,
      filmBarVisible: true,
      filmBarControls: true,
      viewportWidth: 390,
    });
    assert.equal(phone["--sim-inset-left"], `${SIDEBAR_WIDTH_PX}px`);
    assert.equal(phone["--sim-inset-right"], `${SIDEBAR_WIDTH_PX}px`);
    assert.equal(phone["--film-bar-left"], "8px");
    assert.equal(phone["--film-bar-right"], "8px");
    assert.equal(
      phone["--sim-inset-bottom"],
      `${FILM_BAR_HEIGHT_PX.narrow + FILM_BAR_BOTTOM_GAP_PX + ATTRIBUTION_FILM_GAP_PX}px`,
    );
    const desk = mapInsetVars({
      sidebarOpen: true,
      toolsOpen: false,
      filmBarVisible: true,
      filmBarControls: false,
      viewportWidth: 1280,
    });
    assert.equal(desk["--sim-inset-left"], `${SIDEBAR_WIDTH_PX}px`);
    assert.equal(desk["--sim-inset-right"], "0px");
    assert.equal(desk["--sidebar-width"], `${SIDEBAR_WIDTH_PX}px`);
    assert.equal(desk["--film-bar-left"], `${SIDEBAR_WIDTH_PX}px`);
    assert.equal(desk["--film-bar-right"], "8px");
    assert.equal(
      desk["--sim-inset-bottom"],
      `${FILM_BAR_HEIGHT_PX.compact + FILM_BAR_BOTTOM_GAP_PX + ATTRIBUTION_FILM_GAP_PX}px`,
    );
  });

  it("à 1280 px la barre part au bord du tiroir, sous 600 elle reste en gouttière", () => {
    assert.deepEqual(
      filmBarEdgeStyle({ sidebarOpen: true, toolsOpen: true, viewportWidth: 1280 }),
      { left: `${SIDEBAR_WIDTH_PX}px`, right: `${SIDEBAR_WIDTH_PX}px` },
    );
    assert.deepEqual(
      filmBarEdgeStyle({ sidebarOpen: true, toolsOpen: true, viewportWidth: 390 }),
      { left: "8px", right: "8px" },
    );
    const css = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "../index.css"), "utf8");
    const deskAt = css.indexOf("@media (min-width: 600px)");
    assert.ok(deskAt > css.indexOf("@media (max-width: 599px)"));
    const desk = css.slice(deskAt);
    assert.match(desk, /width:\s*var\(--sidebar-width,\s*320px\)\s*!important/);
    assert.match(desk, /max-width:\s*var\(--sidebar-width,\s*320px\)\s*!important/);
    assert.match(desk, /min-width:\s*0\s*!important/);
    assert.match(desk, /left:\s*var\(--film-bar-left,\s*8px\)\s*!important/);
    assert.match(desk, /right:\s*var\(--film-bar-right,\s*8px\)\s*!important/);
    assert.match(desk, /width:\s*calc\(100% - var\(--film-bar-left,\s*8px\) - var\(--film-bar-right,\s*8px\)\)\s*!important/);
    assert.match(desk, /flex-wrap:\s*nowrap/);
    assert.match(desk, /\.naviguide-film-bar button \{\s*padding-left:\s*3px;\s*padding-right:\s*3px;\s*\}/);
  });
});

/**
 * Audit item 7: with the keyboard, Tab must get past the map, and Enter on a stop flag
 * must open the stop.
 */
import { fireEvent, render, waitFor } from "@testing-library/react";
import L from "leaflet";
import { I18nextProvider } from "react-i18next";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import { MapScene, activateWithKeyboard, focusedMarkerKey, keepFocus, outOfTabOrder } from "./MapScene.jsx";

vi.mock("../components/ProjectMapPopup.jsx", () => ({ ProjectMapPopup: () => null }));
vi.mock("../components/MarinaMapPopup.jsx", () => ({ MarinaMapPopup: () => null }));

const point = (lon, lat, properties) => ({ type: "Feature", geometry: { type: "Point", coordinates: [lon, lat] }, properties });
const projects = { type: "FeatureCollection", features: [point(1, 2, { id: "p-1", title: "Reef survey" }), point(3, 4, { id: "p-2", title: "Plastics Initiative" })] };
const marinas = { type: "FeatureCollection", features: [point(-1.15, 46.15, { id: "m-1", name: "Bassin des Tamaris" })] };
const stops = [
  { name: "La Rochelle", lat: 46.16, lon: -1.15, milestoneId: "dep-la-rochelle", flags: ["/flags/fr.svg"] },
  { name: "Ajaccio (Corse)", lat: 41.92, lon: 8.73, milestoneId: "dep-ajaccio-corse", flags: ["/flags/fr.svg"] },
];
const segments = [{ coords: [[-1.15, 46.16], [8.73, 41.92]] }];
const boat = { lat: 45, lon: 2, bearing: 90 };

describe("MapScene with the keyboard", () => {
  let maps;
  beforeEach(async () => {
    maps = [];
    await i18n.changeLanguage("en");
    const create = L.map.bind(L);
    vi.spyOn(L, "map").mockImplementation((...args) => {
      const map = create(...args);
      maps.push(map);
      return map;
    });
  });
  afterEach(() => {
    vi.restoreAllMocks();
    document.body.innerHTML = "";
  });

  function show(props = {}) {
    const onSelectStop = vi.fn();
    const onSelectBoat = vi.fn();
    render(
      <I18nextProvider i18n={i18n}>
        <MapScene segments={segments} stops={stops} boat={boat} projects={projects} marinas={marinas} theme="dark" showProjects showMarinas onSelectStop={onSelectStop} onSelectBoat={onSelectBoat} {...props} />
      </I18nextProvider>,
    );
    return { onSelectStop, onSelectBoat };
  }
  const flag = (id) => document.querySelector(`.flag-divicon[data-stop-id="${id}"]`);
  const boatMarker = () => document.querySelector(".boat-divicon");

  it("keeps a focused flag in place when the map is panned", async () => {
    show();
    await waitFor(() => expect(flag("dep-la-rochelle")).not.toBeNull());
    const element = flag("dep-la-rochelle");
    element.focus();
    expect(document.activeElement).toBe(element);
    maps[0].fire("moveend");
    // Not redrawn: the same element, still focused. Before, it was thrown away here.
    expect(flag("dep-la-rochelle")).toBe(element);
    expect(document.activeElement).toBe(element);
  });

  it("gives focus back to the same flag when a zoom redraws the flags", async () => {
    show();
    await waitFor(() => expect(flag("dep-ajaccio-corse")).not.toBeNull());
    const before = flag("dep-ajaccio-corse");
    before.focus();
    maps[0].fire("zoomend");
    const after = flag("dep-ajaccio-corse");
    expect(after).not.toBe(before);
    expect(document.activeElement).toBe(after);
    expect(focusedMarkerKey("stopId")).toBe("dep-ajaccio-corse");
  });

  it("does not take focus when no flag had it", async () => {
    show();
    await waitFor(() => expect(flag("dep-la-rochelle")).not.toBeNull());
    maps[0].fire("zoomend");
    expect(document.activeElement).toBe(document.body);
  });

  it("keeps the boat focused across a zoom, and leaves it alone after a pan", async () => {
    show();
    await waitFor(() => expect(boatMarker()).not.toBeNull());
    const element = boatMarker();
    element.focus();
    maps[0].fire("moveend");
    expect(boatMarker()).toBe(element);
    maps[0].fire("zoomend");
    expect(boatMarker()).not.toBe(element);
    expect(document.activeElement).toBe(boatMarker());
  });

  it.each(["Enter", " "])("opens a stop with %j on its flag", async (key) => {
    const { onSelectStop } = show();
    await waitFor(() => expect(flag("dep-la-rochelle")).not.toBeNull());
    fireEvent.keyDown(flag("dep-la-rochelle"), { key });
    expect(onSelectStop).toHaveBeenCalledTimes(1);
    expect(onSelectStop.mock.calls[0][0]).toMatchObject({ milestoneId: "dep-la-rochelle" });
  });

  it("ignores other keys on a flag, and Enter still works after a redraw", async () => {
    const { onSelectStop } = show();
    await waitFor(() => expect(flag("dep-la-rochelle")).not.toBeNull());
    fireEvent.keyDown(flag("dep-la-rochelle"), { key: "a" });
    fireEvent.keyDown(flag("dep-la-rochelle"), { key: "Tab" });
    expect(onSelectStop).not.toHaveBeenCalled();
    maps[0].fire("zoomend");
    fireEvent.keyDown(flag("dep-la-rochelle"), { key: "Enter" });
    expect(onSelectStop).toHaveBeenCalledTimes(1);
  });

  it("opens the boat with Enter", async () => {
    const { onSelectBoat } = show();
    await waitFor(() => expect(boatMarker()).not.toBeNull());
    fireEvent.keyDown(boatMarker(), { key: "Enter" });
    expect(onSelectBoat).toHaveBeenCalledTimes(1);
  });

  it("keeps flags and boat in the Tab order and takes every project and marina dot out of it", async () => {
    show();
    await waitFor(() => expect(document.querySelectorAll(".project-dot")).toHaveLength(2));
    for (const dot of document.querySelectorAll(".project-dot, .marina-dot")) {
      expect(dot.getAttribute("tabindex")).toBe("-1");
    }
    expect(document.querySelectorAll(".marina-dot")).toHaveLength(1);
    expect(flag("dep-la-rochelle").getAttribute("tabindex")).toBe("0");
    expect(boatMarker().getAttribute("tabindex")).toBe("0");
    // Named for a screen reader, as before.
    expect(flag("dep-la-rochelle").getAttribute("aria-label")).toBe("Open stop: La Rochelle");
  });
});

describe("marker helpers", () => {
  afterEach(() => {
    document.body.innerHTML = "";
  });
  const marker = () => {
    const element = document.body.appendChild(document.createElement("div"));
    element.tabIndex = 0;
    return { getElement: () => element, element };
  };

  it("keepFocus names the element and focuses it only for the key that had focus", () => {
    const a = marker();
    const b = marker();
    keepFocus(a, "stopId", "dep-a", "dep-b");
    keepFocus(b, "stopId", "dep-b", "dep-b");
    expect(a.element.dataset.stopId).toBe("dep-a");
    expect(document.activeElement).toBe(b.element);
    expect(focusedMarkerKey("stopId")).toBe("dep-b");
    expect(focusedMarkerKey("boatMarker")).toBeNull();
  });

  it("tolerates a marker with no element yet", () => {
    expect(() => keepFocus({ getElement: () => null }, "stopId", "x", "x")).not.toThrow();
    expect(() => activateWithKeyboard({}, () => {})).not.toThrow();
    expect(() => outOfTabOrder({})).not.toThrow();
  });

  it("activateWithKeyboard stops the key from reaching the map", () => {
    const m = marker();
    const activate = vi.fn();
    const onMapKey = vi.fn();
    document.body.addEventListener("keydown", onMapKey);
    activateWithKeyboard(m, activate);
    const notPrevented = fireEvent.keyDown(m.element, { key: "Enter" });
    expect(activate).toHaveBeenCalledTimes(1);
    expect(notPrevented).toBe(false);
    expect(onMapKey).not.toHaveBeenCalled();
    document.body.removeEventListener("keydown", onMapKey);
  });
});

import { describe, expect, it } from "vitest";
import { boatPosition } from "./boatPosition.js";

const stops = [
  { name: "Saint-Maur (Berry, Indre)", filmNm: 0 },
  { name: "La Rochelle", filmNm: 120 },
  { name: "Ajaccio (Corse)", filmNm: 1500 },
];

describe("boatPosition", () => {
  it("says nothing without a sample or without stops", () => {
    expect(boatPosition(stops, null)).toBeNull();
    expect(boatPosition([], { status: "live", filmNm: 10 })).toBeNull();
    expect(boatPosition(stops, { status: "live" })).toBeNull();
  });

  it("waits at the first stop before departure", () => {
    expect(boatPosition(stops, { status: "waiting", atQuay: true, filmNm: 0 })).toEqual({
      kind: "waiting",
      stop: "Saint-Maur (Berry, Indre)",
    });
  });

  it("is under way between the last stop reached and the next one", () => {
    expect(boatPosition(stops, { status: "live", atQuay: false, filmNm: 131.3 })).toEqual({
      kind: "underway",
      from: "La Rochelle",
      to: "Ajaccio (Corse)",
    });
    expect(boatPosition(stops, { status: "live", atQuay: false, filmNm: 60 })).toEqual({
      kind: "underway",
      from: "Saint-Maur (Berry, Indre)",
      to: "La Rochelle",
    });
  });

  it("is at a stop while it is held there", () => {
    expect(boatPosition(stops, { status: "live", atQuay: true, filmNm: 120.2 })).toEqual({
      kind: "stop",
      stop: "La Rochelle",
    });
  });

  it("is at the last stop once the voyage is over", () => {
    expect(boatPosition(stops, { status: "arrived", atQuay: true, filmNm: 1500 })).toEqual({
      kind: "stop",
      stop: "Ajaccio (Corse)",
    });
    expect(boatPosition(stops, { status: "live", atQuay: false, filmNm: 1600 })).toEqual({
      kind: "stop",
      stop: "Ajaccio (Corse)",
    });
  });

  it("uses the sailed distance when a stop has no film distance", () => {
    const plain = [{ name: "A", nm: 0 }, { name: "B", nm: 50 }];
    expect(boatPosition(plain, { status: "live", filmNm: 20 })).toEqual({ kind: "underway", from: "A", to: "B" });
  });
});

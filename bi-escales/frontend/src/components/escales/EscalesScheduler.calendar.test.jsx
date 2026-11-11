/**
 * A2 / B3: the stopover calendar (Bryntum, behind features.bryntum). Each stop is a bar
 * from arrival to departure; the cabin checkouts are one step away, not on the page by default.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../../i18n";
import EscalesScheduler, { buildEvents } from "./EscalesScheduler.jsx";

const timelineProps = [];
vi.mock("./BryntumTimeline.jsx", () => ({
  default: (props) => {
    timelineProps.push(props);
    return <div data-testid="timeline">{props.events.map((event) => event.name).join(",")}</div>;
  },
}));
vi.mock("../PledgeButton", () => ({
  PledgeButton: ({ values }) => <button type="button" data-testid="cabin-checkout">{values.milestone_id}</button>,
}));

const escales = [
  { milestone_id: "dep-la-rochelle", slug: "la-rochelle", name: "La Rochelle", arrival_iso: "2026-11-12T12:00:00Z" },
  { milestone_id: "dep-ajaccio-corse", slug: "ajaccio-corse", name: "Ajaccio (Corse)", arrival_iso: "2026-11-29T02:02:00Z" },
  { milestone_id: "ret-la-rochelle", slug: "la-rochelle-retour", name: "La Rochelle (retour)", arrival_iso: "2027-08-27T08:23:00Z" },
];
const legs = [
  { id: "leg-la-rochelle-to-ajaccio-corse", from_slug: "la-rochelle", to_slug: "ajaccio-corse", from_name: "La Rochelle", to_name: "Ajaccio (Corse)", departure_iso: "2026-11-12T12:00:00Z", arrival_iso: "2026-11-29T02:02:00Z" },
  { id: "leg-ajaccio-corse-to-fort-de-france-martinique", from_slug: "ajaccio-corse", to_slug: "fort-de-france-martinique", from_name: "Ajaccio (Corse)", to_name: "Fort-de-France (Martinique)", departure_iso: "2026-12-02T02:02:00Z", arrival_iso: "2026-12-30T08:34:00Z" },
];
const schedule = { export: { escales }, legs, prices: { prices: [{ kind: "cabin_leg", amount_eur: "80.00" }] } };
const iso = (date) => date.toISOString();

describe("buildEvents: how long the boat stays", () => {
  it("draws a stop from its arrival to the departure of the leg that leaves it", () => {
    const [, ajaccio] = buildEvents(escales, legs);
    expect(iso(ajaccio.startDate)).toBe("2026-11-29T02:02:00.000Z");
    expect(iso(ajaccio.endDate)).toBe("2026-12-02T02:02:00.000Z");
    expect(iso(ajaccio.departureDate)).toBe("2026-12-02T02:02:00.000Z");
  });

  it("keeps a stop the boat leaves within the day one day wide, and still knows its departure", () => {
    const [rochelle] = buildEvents(escales, legs);
    expect(iso(rochelle.startDate)).toBe("2026-11-12T12:00:00.000Z");
    expect(iso(rochelle.endDate)).toBe("2026-11-13T12:00:00.000Z");
    expect(iso(rochelle.departureDate)).toBe("2026-11-12T12:00:00.000Z");
  });

  it("draws the last stop one day wide and invents no departure", () => {
    const last = buildEvents(escales, legs).at(-1);
    expect(iso(last.endDate)).toBe("2027-08-28T08:23:00.000Z");
    expect(last.departureDate).toBeNull();
  });

  it("prefers a departure the stop itself carries, and ignores one before the arrival", () => {
    const [own] = buildEvents([{ ...escales[1], departure_iso: "2026-12-05T00:00:00Z" }], legs);
    expect(iso(own.endDate)).toBe("2026-12-05T00:00:00.000Z");
    const [bad] = buildEvents([{ ...escales[1], departure_iso: "2026-11-01T00:00:00Z" }], []);
    expect(bad.departureDate).toBeNull();
    expect(iso(bad.endDate)).toBe("2026-11-30T02:02:00.000Z");
  });

  it("finds the leg by the stop's name when it has no slug", () => {
    const [byName] = buildEvents([{ milestone_id: "x", name: "Ajaccio (Corse)", arrival_iso: "2026-11-29T02:02:00Z" }], legs);
    expect(iso(byName.endDate)).toBe("2026-12-02T02:02:00.000Z");
  });

  it("still works with no legs at all", () => {
    expect(buildEvents(escales).map((event) => iso(event.endDate))).toEqual([
      "2026-11-13T12:00:00.000Z",
      "2026-11-30T02:02:00.000Z",
      "2027-08-28T08:23:00.000Z",
    ]);
  });
});

describe("EscalesScheduler layout", () => {
  beforeEach(async () => {
    timelineProps.length = 0;
    await i18n.changeLanguage("en");
  });
  afterEach(() => vi.clearAllMocks());

  const show = (props = {}) =>
    render(
      <I18nextProvider i18n={i18n}>
        <EscalesScheduler schedule={schedule} planningEnabled onSelectEscale={() => {}} onAuthorized={() => {}} {...props} />
      </I18nextProvider>,
    );
  const openCabins = () => {
    const cabins = screen.getByTestId("schedule-cabins");
    cabins.open = true;
    fireEvent(cabins, new Event("toggle"));
    return cabins;
  };

  it("puts the calendar first and mounts no checkout until the visitor asks for the cabins", () => {
    show();
    const section = screen.getByRole("heading", { name: "Stopover calendar" }).closest("section");
    expect([...section.children].map((child) => child.tagName)).toEqual(["HEADER", "P", "DIV", "DETAILS"]);
    expect(screen.getByTestId("timeline")).toHaveTextContent("La Rochelle,Ajaccio (Corse),La Rochelle (retour)");
    expect(screen.queryByTestId("cabin-checkout")).toBeNull();
    expect(screen.getByTestId("schedule-cabins-count")).toHaveTextContent("2");
    expect(screen.getByText("Book a cabin on a leg")).toBeInTheDocument();
  });

  it("offers one cabin checkout per leg once opened, with the same values as before", () => {
    show();
    openCabins();
    expect(screen.getAllByTestId("cabin-checkout").map((button) => button.textContent)).toEqual([
      "leg-la-rochelle-to-ajaccio-corse",
      "leg-ajaccio-corse-to-fort-de-france-martinique",
    ]);
    expect(screen.getAllByTestId("cabin-price")[0]).toHaveTextContent("80.00 EUR");
  });

  it("takes the checkouts off the page again when the list is closed", () => {
    show();
    const cabins = openCabins();
    cabins.open = false;
    fireEvent(cabins, new Event("toggle"));
    expect(screen.queryByTestId("cabin-checkout")).toBeNull();
  });

  it("says a stop can be opened only where it can", () => {
    show();
    expect(screen.getByText("One bar per stop, from arrival to departure. Select a stop to open it.")).toBeInTheDocument();
  });

  it("on the treasurer page: no cabins, no promise to open a stop, and room for every name and row", () => {
    show({ showCabins: false, wide: true, onSelectEscale: undefined, onAuthorized: undefined });
    expect(screen.queryByTestId("schedule-cabins")).toBeNull();
    expect(screen.getByText("One bar per stop, from arrival to departure.")).toBeInTheDocument();
    expect(screen.queryByText(/Select a stop/)).toBeNull();
    expect(timelineProps.at(-1)).toMatchObject({ nameWidth: 220, maxHeight: Number.POSITIVE_INFINITY });
  });

  it("keeps the rail's compact timeline by default", () => {
    show();
    expect(timelineProps.at(-1)).not.toHaveProperty("nameWidth");
    expect(timelineProps.at(-1)).not.toHaveProperty("maxHeight");
  });

  it("has no cabin list when the schedule has no leg", () => {
    show({ schedule: { export: { escales }, legs: [] } });
    expect(screen.queryByTestId("schedule-cabins")).toBeNull();
  });

  it("is written in French too", async () => {
    await i18n.changeLanguage("fr");
    show();
    expect(screen.getByText("Une barre par escale, de l’arrivée au départ. Sélectionnez une escale pour l’ouvrir.")).toBeInTheDocument();
    expect(screen.getByText("Réserver une cabine sur une étape")).toBeInTheDocument();
  });

  it("renders nothing when the flag is off", () => {
    const view = show({ planningEnabled: false });
    expect(view.container).toBeEmptyDOMElement();
  });
});

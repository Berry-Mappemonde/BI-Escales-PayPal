import { fireEvent, render, screen } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import { EscaleSheet } from "./EscaleSheet.jsx";

vi.mock("../api/escales", () => ({
  fetchClock: vi.fn().mockResolvedValue({ now: "2026-11-20T08:00:00Z" }),
  fetchFund: vi.fn().mockResolvedValue({}),
  listMilestones: vi.fn().mockResolvedValue([]),
}));

vi.mock("./PledgeButton", () => ({
  PledgeButton: ({ values }) => (
    <div data-testid="pledge-values">{JSON.stringify(values)}</div>
  ),
}));

const stop = { name: "La Rochelle", lat: 46.15, lon: -1.15, milestoneId: "dep-la-rochelle" };

const priceCatalog = {
  prices: [
    { kind: "berth", amount_eur: "30.00" },
    { kind: "cabin_leg", amount_eur: "80.00" },
    { kind: "night", amount_eur: "60.00" },
    { kind: "meal", amount_eur: "60.00" },
    { kind: "care", amount_eur: "40.00" },
  ],
};

const schedule = {
  legs: [{ id: "leg-la-rochelle-to-ajaccio-corse", from_name: "La Rochelle", to_name: "Ajaccio (Corse)" }],
};

const mooringFiche = {
  name: "La Rochelle",
  sections: {
    mooring: {
      marinas: [
        {
          name: "Port des Minimes",
          lat: 46.14,
          lon: -1.16,
          nm: 0.44,
          url: "https://portlarochelle.com",
          maps_url: "https://www.google.com/maps/place/Minimes",
          canal_vhf: "9",
          places_visiteurs: 8,
          services: ["eau", "électricité"],
          resume_avis: "Accueil soigné.",
        },
      ],
    },
  },
};

describe("EscaleSheet", () => {
  it("envoie le type de promesse avec description auto", async () => {
    await i18n.changeLanguage("fr");
    const onKind = vi.fn();
    render(
      <I18nextProvider i18n={i18n}>
        <EscaleSheet
          stop={stop}
          fiche={null}
          pledge={{
            amount: "20.00",
            milestoneId: "dep-la-rochelle",
            contributor: "",
            kind: "mile",
            onAmount: () => {},
            onMilestoneId: () => {},
            onContributor: () => {},
            onKind,
          }}
        />
      </I18nextProvider>,
    );
    expect(screen.queryByTestId("captain-review")).toBeNull();
    fireEvent.change(screen.getByTestId("pledge-kind"), { target: { value: "night" } });
    expect(onKind).toHaveBeenCalledWith("night");
    const sent = JSON.parse(screen.getByTestId("pledge-values").textContent || "{}");
    expect(sent.kind).toBe("mile");
    expect(sent.description).toContain("La Rochelle");
    expect(sent.target_id).toBe("dep-la-rochelle");
  });

  it("une nuit affiche 60.00 en lecture seule et l'envoie", async () => {
    await i18n.changeLanguage("fr");
    render(
      <I18nextProvider i18n={i18n}>
        <EscaleSheet
          stop={stop}
          fiche={null}
          priceCatalog={priceCatalog}
          pledge={{
            amount: "20.00",
            milestoneId: "dep-la-rochelle",
            contributor: "",
            kind: "night",
            onAmount: () => {},
            onMilestoneId: () => {},
            onContributor: () => {},
            onKind: () => {},
          }}
        />
      </I18nextProvider>,
    );
    const field = screen.getByTestId("pledge-amount");
    expect(field).toHaveProperty("readOnly", true);
    expect(field).toHaveValue("60.00");
    const sent = JSON.parse(screen.getByTestId("pledge-values").textContent || "{}");
    expect(sent.kind).toBe("night");
    expect(sent.amount_eur).toBe("60.00");
  });

  it("repro Nov 4 : état mile 20.00 mais type berth affiche et envoie 30.00", async () => {
    await i18n.changeLanguage("fr");
    render(
      <I18nextProvider i18n={i18n}>
        <EscaleSheet
          stop={stop}
          fiche={null}
          priceCatalog={priceCatalog}
          pledge={{
            amount: "20.00",
            milestoneId: "dep-la-rochelle",
            contributor: "",
            kind: "berth",
            onAmount: () => {},
            onMilestoneId: () => {},
            onContributor: () => {},
            onKind: () => {},
          }}
        />
      </I18nextProvider>,
    );
    expect(screen.getByTestId("pledge-amount")).toHaveValue("30.00");
    const sent = JSON.parse(screen.getByTestId("pledge-values").textContent || "{}");
    expect(sent.kind).toBe("berth");
    expect(sent.amount_eur).toBe("30.00");
    expect(sent.amount_eur).not.toBe("80.00");
  });

  it("cabin_leg affiche et envoie 80.00 même si l'état utilisateur vaut 20.00", async () => {
    await i18n.changeLanguage("fr");
    render(
      <I18nextProvider i18n={i18n}>
        <EscaleSheet
          stop={stop}
          fiche={null}
          priceCatalog={priceCatalog}
          schedule={schedule}
          pledge={{
            amount: "20.00",
            milestoneId: "dep-la-rochelle",
            contributor: "",
            kind: "cabin_leg",
            onAmount: () => {},
            onMilestoneId: () => {},
            onContributor: () => {},
            onKind: () => {},
          }}
        />
      </I18nextProvider>,
    );
    expect(screen.getByTestId("pledge-amount")).toHaveValue("80.00");
    const sent = JSON.parse(screen.getByTestId("pledge-values").textContent || "{}");
    expect(sent.amount_eur).toBe("80.00");
    expect(sent.milestone_id).toBe("leg-la-rochelle-to-ajaccio-corse");
  });

  it("affiche l'arrivée estimée et le carnet en FR", async () => {
    await i18n.changeLanguage("fr");
    render(
      <I18nextProvider i18n={i18n}>
        <EscaleSheet
          stop={stop}
          fiche={null}
          arrivalIso="2026-11-12T08:00:00.000Z"
          logbookEntries={[
            {
              t: "2026-11-10T08:00:00.000Z",
              pos: { lat: 46.2, lon: -1.1 },
              label_fr: "Position — en route vers La Rochelle",
              label_en: "Position — underway for La Rochelle",
            },
          ]}
        />
      </I18nextProvider>,
    );
    expect(screen.getByTestId("escale-estimated-arrival")).toHaveTextContent(/Arrivée prévue/);
    expect(await screen.findByTestId("escale-logbook")).toHaveTextContent("en route vers La Rochelle");
  });

  it("shows estimated arrival and logbook in EN", async () => {
    await i18n.changeLanguage("en");
    render(
      <I18nextProvider i18n={i18n}>
        <EscaleSheet
          stop={stop}
          fiche={null}
          arrivalIso="2026-11-12T08:00:00.000Z"
          logbookEntries={[
            {
              t: "2026-11-12T08:00:00.000Z",
              pos: { lat: 46.15, lon: -1.15 },
              label_fr: "Escale — arrivée La Rochelle",
              label_en: "Stopover — arrival at La Rochelle",
            },
          ]}
        />
      </I18nextProvider>,
    );
    expect(screen.getByTestId("escale-estimated-arrival")).toHaveTextContent(/Scheduled arrival/);
    expect(await screen.findByTestId("escale-logbook")).toHaveTextContent("arrival at La Rochelle");
  });

  it("affiche les infos marina enrichies en FR (Amarrage)", async () => {
    await i18n.changeLanguage("fr");
    render(
      <I18nextProvider i18n={i18n}>
        <EscaleSheet stop={stop} fiche={mooringFiche} />
      </I18nextProvider>,
    );
    expect(screen.getByText("Amarrage")).toBeInTheDocument();
    expect(screen.getByText(/VHF: 9/)).toBeInTheDocument();
    expect(screen.getByText(/Places visiteurs: 8/)).toBeInTheDocument();
    expect(screen.getByText(/Services: eau, électricité/)).toBeInTheDocument();
  });

  it("shows enriched marina facts in EN (Mooring)", async () => {
    await i18n.changeLanguage("en");
    render(
      <I18nextProvider i18n={i18n}>
        <EscaleSheet stop={stop} fiche={mooringFiche} />
      </I18nextProvider>,
    );
    expect(screen.getByText("Mooring")).toBeInTheDocument();
    expect(screen.getByText(/Visitor berths: 8/)).toBeInTheDocument();
    expect(screen.getByText(/Services: eau, électricité/)).toBeInTheDocument();
  });
});

 it.each([["mile", "4.00"], ["berth", "120.00"], ["night", "240.00"], ["meal", "240.00"], ["care", "160.00"], ["cabin_leg", "320.00"]])("multiplies %s unit price by quantity", (kind, total) => {
  render(<EscaleSheet stop={stop} fiche={null} priceCatalog={priceCatalog} schedule={schedule}
    pledge={{kind, amount: "1.00", milestoneId: "dep-la-rochelle", contributor: "", onKind: vi.fn(), onAmount: vi.fn(), onContributor: vi.fn()}} />);
  fireEvent.change(screen.getByTestId("pledge-quantity"), {target: {value: "4"}});
  expect(screen.getByTestId("pledge-amount")).toHaveValue(total);
  expect(screen.getByTestId("pledge-amount")).toHaveAttribute("readonly");
  const payload=JSON.parse(screen.getByTestId("pledge-values").textContent);
  expect(payload.quantity).toBe(4); expect(payload.amount_eur).toBe(total);
 });

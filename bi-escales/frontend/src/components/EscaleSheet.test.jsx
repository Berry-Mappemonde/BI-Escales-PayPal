import { fireEvent, render, screen } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import { EscaleSheet } from "./EscaleSheet.jsx";

vi.mock("./PledgeButton", () => ({
  PledgeButton: ({ values }) => (
    <div data-testid="pledge-values">{JSON.stringify(values)}</div>
  ),
}));

const stop = { name: "La Rochelle", lat: 46.15, lon: -1.15, milestoneId: "dep-la-rochelle" };

const logbook = [
  {
    t: "2026-11-10T08:00:00.000Z",
    pos: { lat: 46.2, lon: -1.1 },
    label_fr: "Position — en route vers La Rochelle",
    label_en: "Position — underway for La Rochelle",
  },
  {
    t: "2026-11-12T08:00:00.000Z",
    pos: { lat: 46.15, lon: -1.15 },
    label_fr: "Escale — arrivée La Rochelle",
    label_en: "Stopover — arrival at La Rochelle",
  },
];

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
    expect(screen.getByText(/HelloAsso/)).toBeInTheDocument();
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

  it("affiche l'arrivée estimée et le carnet en FR", async () => {
    await i18n.changeLanguage("fr");
    render(
      <I18nextProvider i18n={i18n}>
        <EscaleSheet
          stop={stop}
          fiche={null}
          arrivalIso="2026-11-12T08:00:00.000Z"
          logbookEntries={logbook}
        />
      </I18nextProvider>,
    );
    expect(screen.getByTestId("escale-estimated-arrival")).toHaveTextContent(/Arrivée estimée/);
    expect(screen.getByTestId("escale-logbook")).toHaveTextContent("en route vers La Rochelle");
    expect(screen.getByTestId("escale-logbook")).toHaveTextContent("arrivée La Rochelle");
  });

  it("shows estimated arrival and logbook in EN", async () => {
    await i18n.changeLanguage("en");
    render(
      <I18nextProvider i18n={i18n}>
        <EscaleSheet
          stop={stop}
          fiche={null}
          arrivalIso="2026-11-12T08:00:00.000Z"
          logbookEntries={logbook}
        />
      </I18nextProvider>,
    );
    expect(screen.getByTestId("escale-estimated-arrival")).toHaveTextContent(/Estimated arrival/);
    expect(screen.getByTestId("escale-logbook")).toHaveTextContent("underway for La Rochelle");
    expect(screen.getByTestId("escale-logbook")).toHaveTextContent("arrival at La Rochelle");
  });
});

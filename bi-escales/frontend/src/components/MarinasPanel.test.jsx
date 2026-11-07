import { fireEvent, render, screen } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { describe, expect, it } from "vitest";
import i18n from "../i18n";
import MarinasPanel from "./MarinasPanel.jsx";

const marinas = {
  type: "FeatureCollection",
  features: [
    {
      type: "Feature",
      geometry: { type: "Point", coordinates: [-1.15, 46.16] },
      properties: { id: "m1", name: "Port des Minimes", osm_id: "1" },
    },
  ],
};

describe("MarinasPanel", () => {
  it("ouvre la réservation à 30 EUR pour la marina choisie", async () => {
    await i18n.changeLanguage("fr");
    render(
      <I18nextProvider i18n={i18n}>
        <MarinasPanel marinas={marinas} milestoneId="dep-la-rochelle" onFlyTo={() => {}} />
      </I18nextProvider>,
    );
    expect(screen.queryByTestId("marina-reserve")).toBeNull();
    fireEvent.click(screen.getByTestId("marina-row-m1"));
    expect(screen.getByTestId("marina-reserve")).toHaveTextContent("30,00 EUR");
    expect(screen.getByTestId("marina-reserve")).toHaveAttribute("data-kind", "berth");
    expect(screen.getByTestId("paypal-buttons")).toHaveAttribute("data-kind", "berth");
    expect(screen.getByText(/Amarrage \(simulation\) — Port des Minimes/)).toBeInTheDocument();
  });

  it("affiche la légende FR/EN des marinas vérifiées", async () => {
    await i18n.changeLanguage("fr");
    const verified = {
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          geometry: { type: "Point", coordinates: [-1.1661, 46.1468] },
          properties: {
            id: "m2",
            name: "Minimes",
            safe_google_place: true,
          },
        },
        ...marinas.features,
      ],
    };
    render(
      <I18nextProvider i18n={i18n}>
        <MarinasPanel marinas={verified} milestoneId="dep-la-rochelle" onFlyTo={() => {}} />
      </I18nextProvider>,
    );
    expect(screen.getByTestId("marinas-legend")).toBeInTheDocument();
    expect(screen.getByText(/Fiche Google vérifiée/)).toBeInTheDocument();
    expect(screen.getByText(/\(1\)/)).toBeInTheDocument();
  });

  it("affiche la légende des fiches Google rejetées avec le décompte", async () => {
    await i18n.changeLanguage("en");
    const rejected = {
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          geometry: { type: "Point", coordinates: [-61.53, 16.22] },
          properties: {
            id: "m3",
            name: "Bas-du-Fort",
            maps_place_rejected: "suspicious_name",
          },
        },
        ...marinas.features,
      ],
    };
    render(
      <I18nextProvider i18n={i18n}>
        <MarinasPanel marinas={rejected} milestoneId="dep-pointe-a-pitre" onFlyTo={() => {}} />
      </I18nextProvider>,
    );
    expect(screen.getByText(/Rejected Google place — red on the map/)).toBeInTheDocument();
    expect(screen.getByText(/Marina — red on the map/)).toBeInTheDocument();
    expect(screen.getAllByText(/\(1\)/).length).toBeGreaterThanOrEqual(1);
  });
});

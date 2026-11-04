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
    expect(screen.getByText(/Amarrage \(simulation\) — Port des Minimes/)).toBeInTheDocument();
  });
});

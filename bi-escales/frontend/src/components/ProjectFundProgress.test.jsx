import { render, screen } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { describe, expect, it } from "vitest";
import i18n from "../i18n";
import { ProjectFundProgress } from "./ProjectFundProgress";

describe("ProjectFundProgress", () => {
  it("masque le lien Channel3 tant que le objectif n'est pas atteint", () => {
    render(
      <I18nextProvider i18n={i18n}>
        <ProjectFundProgress
          properties={{ title: "Gear", channel3_buy_url: "https://buy.example" }}
          fund={{ goal_eur: "100.00", amount_eur: "40.00", funded_pct: 40, currency: "EUR" }}
        />
      </I18nextProvider>,
    );
    expect(screen.getByTestId("project-fund-progress")).toBeInTheDocument();
    expect(screen.queryByTestId("gear-channel3-buy")).toBeNull();
  });

  it("affiche le lien Channel3 à 100%", () => {
    render(
      <I18nextProvider i18n={i18n}>
        <ProjectFundProgress
          properties={{ title: "Gear" }}
          fund={{
            goal_eur: "100.00",
            amount_eur: "100.00",
            funded_pct: 100,
            fully_funded: true,
            channel3_buy_url: "https://buy.example",
            currency: "EUR",
          }}
        />
      </I18nextProvider>,
    );
    expect(screen.getByTestId("gear-channel3-buy")).toBeInTheDocument();
  });
});

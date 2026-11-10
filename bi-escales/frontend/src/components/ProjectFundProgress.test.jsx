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

  it("affiche la devise catalogue sur le montant objectif", () => {
    render(
      <I18nextProvider i18n={i18n}>
        <ProjectFundProgress
          properties={{ title: "Gear", channel3_price: "45.00", channel3_currency: "GBP" }}
          fund={{
            goal_amount: "45.00",
            goal_currency: "GBP",
            amount_eur: "10.00",
            funded_pct: null,
            currency: "EUR",
          }}
        />
      </I18nextProvider>,
    );
    expect(screen.getByTestId("project-fund-goal").textContent).toMatch(/45\.00 GBP/);
    expect(screen.getByTestId("project-fund-goal").textContent).toMatch(/10\.00 EUR/);
  });

  it("n’affiche pas le lien si l’URL est la page d’accueil Channel3", () => {
    render(
      <I18nextProvider i18n={i18n}>
        <ProjectFundProgress
          properties={{ title: "Gear" }}
          fund={{
            goal_eur: "100.00",
            amount_eur: "100.00",
            funded_pct: 100,
            fully_funded: true,
            channel3_buy_url: "https://trychannel3.com/",
            currency: "EUR",
          }}
        />
      </I18nextProvider>,
    );
    expect(screen.queryByTestId("gear-channel3-buy")).toBeNull();
  });

  it("shows the Channel3 picture as a fixed-size, lazy thumbnail named after the item", () => {
    render(
      <I18nextProvider i18n={i18n}>
        <ProjectFundProgress
          properties={{ title: "Dive computer", channel3_image_url: "https://img.example.test/dive.jpg" }}
          fund={{ goal_eur: "100.00", amount_eur: "40.00", funded_pct: 40, currency: "EUR" }}
        />
      </I18nextProvider>,
    );
    const photo = screen.getByTestId("gear-channel3-photo");
    expect(photo).toHaveAttribute("src", "https://img.example.test/dive.jpg");
    expect(photo).toHaveAttribute("alt", "Dive computer");
    expect(photo).toHaveAttribute("loading", "lazy");
    expect(photo).toHaveAttribute("width", "48");
    expect(photo).toHaveAttribute("height", "48");
  });

  it("prefers the fund's picture and the catalogue product name", () => {
    render(
      <I18nextProvider i18n={i18n}>
        <ProjectFundProgress
          properties={{ title: "Gear", channel3_product_name: "Suunto D5", channel3_image_url: "https://img.example.test/old.jpg" }}
          fund={{ goal_eur: "100.00", amount_eur: "40.00", funded_pct: 40, currency: "EUR", channel3_image_url: "https://img.example.test/new.jpg" }}
        />
      </I18nextProvider>,
    );
    const photo = screen.getByTestId("gear-channel3-photo");
    expect(photo).toHaveAttribute("src", "https://img.example.test/new.jpg");
    expect(photo).toHaveAttribute("alt", "Suunto D5");
  });

  it.each([undefined, "", "   "])("shows no picture and no placeholder when the URL is %j", (url) => {
    render(
      <I18nextProvider i18n={i18n}>
        <ProjectFundProgress
          properties={{ title: "Reef survey", channel3_image_url: url }}
          fund={{ goal_eur: "100.00", amount_eur: "40.00", funded_pct: 40, currency: "EUR" }}
        />
      </I18nextProvider>,
    );
    expect(screen.getByTestId("project-fund-goal")).toBeInTheDocument();
    expect(screen.queryByTestId("gear-channel3-photo")).toBeNull();
    expect(screen.queryByRole("img")).toBeNull();
  });

  it("leaves the picture to the caller when it already shows one", () => {
    render(
      <I18nextProvider i18n={i18n}>
        <ProjectFundProgress
          showImage={false}
          properties={{ title: "Dive computer", channel3_image_url: "https://img.example.test/dive.jpg" }}
          fund={{ goal_eur: "100.00", amount_eur: "40.00", funded_pct: 40, currency: "EUR" }}
        />
      </I18nextProvider>,
    );
    expect(screen.queryByRole("img")).toBeNull();
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

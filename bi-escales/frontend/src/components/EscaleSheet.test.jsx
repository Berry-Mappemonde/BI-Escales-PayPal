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

describe("EscaleSheet", () => {
  it("affiche la caisse et envoie le type de promesse", async () => {
    await i18n.changeLanguage("fr");
    const onKind = vi.fn();
    render(
      <I18nextProvider i18n={i18n}>
        <EscaleSheet
          stop={stop}
          fiche={null}
          fund={{
            milestone_id: "dep-la-rochelle",
            currency: "EUR",
            income_eur: "20.00",
            spending_eur: "0.00",
            balance_eur: "20.00",
            income: [{ id: "in-1", amount_eur: "20.00", description: "milles" }],
            spending: [],
          }}
          pledge={{
            amount: "20.00",
            description: "milles",
            milestoneId: "dep-la-rochelle",
            contributor: "",
            kind: "mile",
            onAmount: () => {},
            onDescription: () => {},
            onMilestoneId: () => {},
            onContributor: () => {},
            onKind,
          }}
        />
      </I18nextProvider>,
    );
    expect(screen.getByTestId("common-fund")).toHaveTextContent("20.00");
    expect(screen.getByTestId("common-fund")).toHaveTextContent("milles");
    fireEvent.change(screen.getByTestId("pledge-kind"), { target: { value: "night" } });
    expect(onKind).toHaveBeenCalledWith("night");
    const sent = JSON.parse(screen.getByTestId("pledge-values").textContent || "{}");
    expect(sent.kind).toBe("mile");
    expect(sent.target_id).toBe("dep-la-rochelle");
    expect(sent.milestone_id).toBe("dep-la-rochelle");
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
            description: "nuit",
            milestoneId: "dep-la-rochelle",
            contributor: "",
            kind: "night",
            onAmount: () => {},
            onDescription: () => {},
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
});

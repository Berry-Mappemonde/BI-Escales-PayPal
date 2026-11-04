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
});

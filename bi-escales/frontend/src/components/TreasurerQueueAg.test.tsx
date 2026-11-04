import { render, screen } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { describe, expect, it } from "vitest";
import i18n from "../i18n";
import TreasurerQueueAg from "./TreasurerQueueAg";

describe("TreasurerQueueAg", () => {
  it("monte la grille AG Grid avec les lignes de la file", async () => {
    await i18n.changeLanguage("fr");
    render(
      <I18nextProvider i18n={i18n}>
        <TreasurerQueueAg
          rows={[
            {
              id: "p-1",
              status: "authorized",
              intent: "AUTHORIZE",
              currency: "EUR",
              amount_eur: "20.00",
              description: "milles",
              milestone_id: "dep-la-rochelle",
              verdict: "capture",
            },
          ]}
          busyId={null}
          approveLabel="Approuver"
          onApprove={() => {}}
        />
      </I18nextProvider>,
    );
    expect(screen.getByTestId("treasurer-queue-ag-grid")).toBeInTheDocument();
  });
});

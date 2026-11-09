import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { I18nextProvider } from "react-i18next";
import i18n from "../i18n";
import { MileCertificateDownload } from "./MileCertificateDownload";

vi.mock("../api/escales", () => ({
  issueMileCertificate: vi.fn(() => Promise.resolve({
    token: "opaque-token",
    png: "/api/escales/certificates/opaque-token.png",
    pdf: "/api/escales/certificates/opaque-token.pdf",
    mile_number: 1,
    mile_quantity: 1,
    issue_date: "2026-11-12",
  })),
  certificateAssetUrl: (token: string, fmt: string) => `/api/escales/certificates/${token}.${fmt}`,
}));

function renderBlock(pledge: Parameters<typeof MileCertificateDownload>[0]["pledge"]) {
  return render(
    <I18nextProvider i18n={i18n}>
      <MileCertificateDownload pledge={pledge} contributor="Pat" />
    </I18nextProvider>,
  );
}

describe("MileCertificateDownload", () => {
  it("stays hidden until a mile pledge succeeds", () => {
    const { rerender } = renderBlock(null);
    expect(screen.queryByTestId("mile-certificate-receipt")).toBeNull();
    rerender(
      <I18nextProvider i18n={i18n}>
        <MileCertificateDownload
          pledge={{
            id: "p1",
            kind: "mile",
            status: "created",
            amount_eur: "1.00",
            currency: "EUR",
            milestone_id: "dep-la-rochelle",
          }}
          contributor="Pat"
        />
      </I18nextProvider>,
    );
    expect(screen.queryByTestId("mile-certificate-receipt")).toBeNull();
  });

  it("shows download links after a successful mile purchase", async () => {
    renderBlock({
      id: "p2",
      kind: "mile",
      status: "authorized",
      amount_eur: "2.00",
      currency: "EUR",
      milestone_id: "dep-la-rochelle",
    });
    expect(await screen.findByTestId("mile-certificate-receipt")).toBeInTheDocument();
    expect(screen.getByTestId("mile-certificate-png")).toBeInTheDocument();
    expect(screen.getByTestId("mile-certificate-pdf")).toBeInTheDocument();
  });
});

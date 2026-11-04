import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import { emitPledgeReturn } from "../paypal/pledgeReturnEvents";
import { ProjectMapPopup } from "./ProjectMapPopup.jsx";

vi.mock("./PledgeButton", () => ({
  PledgeButton: ({ values, disabled }) => (
    <button
      type="button"
      data-testid="project-map-paypal-button"
      data-kind={values.kind}
      data-target={values.target_id}
      data-amount={values.amount_eur}
      disabled={disabled}
    >
      PayPal
    </button>
  ),
}));

const sampleProps = {
  id: "e84321a7-83fb-4c3d-bcbd-b6a0e303f96b",
  title: "Plastics Initiative",
  description: "Reduce plastics in the ocean.",
  url: "https://oceanfdn.org/initiatives/plastics-initiative/",
};

describe("ProjectMapPopup", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input) => {
        const href = String(input);
        if (href.includes("/api/escales/projects/") && href.endsWith("/fund")) {
          return {
            ok: true,
            status: 200,
            json: async () => ({
              project_id: sampleProps.id,
              currency: "EUR",
              amount_eur: "42.00",
              donation_count: 3,
              refunded_eur: "0.00",
            }),
          };
        }
        return { ok: false, status: 404, json: async () => ({}) };
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows public donation total from GET /projects/{id}/fund", async () => {
    await i18n.changeLanguage("en");
    render(
      <I18nextProvider i18n={i18n}>
        <ProjectMapPopup properties={sampleProps} contributorDefault="Pat" onAuthorized={() => {}} />
      </I18nextProvider>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("project-map-public-total")).toHaveTextContent("42.00 EUR collected · 3 donations");
    });
    expect(global.fetch).toHaveBeenCalledWith(expect.stringContaining(`/api/escales/projects/${sampleProps.id}/fund`));
  });

  it("hides totals quietly on 404 fund response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: false, status: 404, json: async () => ({}) })),
    );
    await i18n.changeLanguage("en");
    render(
      <I18nextProvider i18n={i18n}>
        <ProjectMapPopup properties={sampleProps} onAuthorized={() => {}} />
      </I18nextProvider>,
    );
    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalled();
    });
    expect(screen.queryByTestId("project-map-public-total")).toBeNull();
  });

  it("refetches public total after a successful pledge return", async () => {
    const fetchMock = vi.fn(async (input) => {
      const href = String(input);
      if (href.includes("/api/escales/projects/") && href.endsWith("/fund")) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            project_id: sampleProps.id,
            currency: "EUR",
            amount_eur: "42.00",
            donation_count: 3,
            refunded_eur: "0.00",
          }),
        };
      }
      return { ok: false, status: 404, json: async () => ({}) };
    });
    vi.stubGlobal("fetch", fetchMock);
    await i18n.changeLanguage("en");
    render(
      <I18nextProvider i18n={i18n}>
        <ProjectMapPopup properties={sampleProps} onAuthorized={() => {}} />
      </I18nextProvider>,
    );
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    emitPledgeReturn({ pledgeId: "any", outcome: "authorized" });
    await waitFor(() => expect(fetchMock.mock.calls.length).toBeGreaterThanOrEqual(2));
  });

  it("shows title, description, external site link, and PayPal control", async () => {
    await i18n.changeLanguage("en");
    render(
      <I18nextProvider i18n={i18n}>
        <ProjectMapPopup properties={sampleProps} contributorDefault="Pat" onAuthorized={() => {}} />
      </I18nextProvider>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("project-map-popup")).toBeInTheDocument();
    });
    expect(screen.getByText("Plastics Initiative")).toBeInTheDocument();
    expect(screen.getByTestId("project-map-description")).toHaveTextContent("Reduce plastics");
    const link = screen.getByTestId("project-map-site-link");
    expect(link).toHaveAttribute("href", sampleProps.url);
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    const btn = screen.getByTestId("project-map-paypal-button");
    expect(btn).toHaveAttribute("data-kind", "project_pledge");
    expect(btn).toHaveAttribute("data-target", sampleProps.id);
    expect(btn).not.toBeDisabled();
  });

  it("blocks PayPal when the amount is invalid", async () => {
    await i18n.changeLanguage("en");
    render(
      <I18nextProvider i18n={i18n}>
        <ProjectMapPopup properties={sampleProps} onAuthorized={() => {}} />
      </I18nextProvider>,
    );
    fireEvent.change(screen.getByTestId("project-map-pledge-amount"), { target: { value: "1,005" } });
    expect(screen.getByTestId("project-map-amount-invalid")).toBeInTheDocument();
    expect(screen.getByTestId("project-map-paypal-button")).toBeDisabled();
  });

  it("affiche le lien et les libellés en français", async () => {
    await i18n.changeLanguage("fr");
    render(
      <I18nextProvider i18n={i18n}>
        <ProjectMapPopup properties={sampleProps} onAuthorized={() => {}} />
      </I18nextProvider>,
    );
    expect(screen.getByTestId("project-map-site-link")).toHaveTextContent(/Site du projet/i);
  });
});

/**
 * Source: Clément lot 4 Nov 2025 — map project popup PayPal (plan canvas inventory).
 */

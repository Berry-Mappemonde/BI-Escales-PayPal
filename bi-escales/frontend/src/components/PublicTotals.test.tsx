/** A14: the public totals per stop, cabin leg, project and for the common fund, in one place. */
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fetchPublicFunds, type PublicFunds } from "../api/escales";
import i18n from "../i18n";
import { PublicTotals, type PublicTotalsProps } from "./PublicTotals";

vi.mock("../api/escales", async (load) => ({ ...(await load<object>()), fetchPublicFunds: vi.fn() }));

const stopNames = { "dep-la-rochelle": "La Rochelle", "dep-ajaccio-corse": "Ajaccio (Corse)" };
const funds: PublicFunds = {
  currency: "EUR",
  stops: [
    { milestone_id: "dep-ajaccio-corse", fund_id: "ajaccio-corse", authorized_eur: "20.00", captured_eur: "30.00", refunded_eur: "0.00" },
    { milestone_id: "la-rochelle", fund_id: "la-rochelle", authorized_eur: "1.00", captured_eur: "0.00", refunded_eur: "0.00" },
    { milestone_id: "dep-atlantis", fund_id: "atlantis", authorized_eur: "0.00", captured_eur: "5.00", refunded_eur: "5.00" },
  ],
  legs: [
    { milestone_id: "leg-la-rochelle-to-ajaccio-corse", fund_id: "leg-la-rochelle-to-ajaccio-corse", authorized_eur: "0.00", captured_eur: "80.00", refunded_eur: "0.00" },
  ],
  projects: [
    { project_id: "p-plastics", amount_eur: "35.00", donation_count: 2, refunded_eur: "0.00" },
    { project_id: "p-unknown", amount_eur: "9.50", donation_count: 1, refunded_eur: "0.00" },
  ],
  common_fund: { authorized_eur: "0.00", captured_eur: "12.00", refunded_eur: "0.00" },
};
const none: PublicFunds = { currency: "EUR", stops: [], legs: [], projects: [], common_fund: { authorized_eur: "0.00", captured_eur: "0.00", refunded_eur: "0.00" } };

function tree(props: PublicTotalsProps = {}) {
  return (
    <I18nextProvider i18n={i18n}>
      <PublicTotals
        stopNames={stopNames}
        projectTitle={(id) => (id === "p-plastics" ? "Plastics Initiative" : undefined)}
        {...props}
      />
    </I18nextProvider>
  );
}
function toggle(open: boolean) {
  const details = screen.getByTestId("public-totals") as HTMLDetailsElement;
  details.open = open;
  fireEvent(details, new Event("toggle"));
}
const row = (id: string) => screen.getByTestId(`public-total-${id}`).textContent;

describe("PublicTotals", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
    vi.mocked(fetchPublicFunds).mockResolvedValue(funds);
  });
  afterEach(() => vi.clearAllMocks());

  it("is closed and reads nothing until the visitor opens it", () => {
    render(tree());
    expect(screen.getByRole("heading", { name: "Where the money goes" })).toBeInTheDocument();
    expect(fetchPublicFunds).not.toHaveBeenCalled();
    expect(screen.queryByTestId("public-totals-body")).toBeNull();
  });

  it("shows each stop by name with what is pledged and what is captured", async () => {
    render(tree());
    toggle(true);
    await screen.findByTestId("public-totals-body");
    expect(row("ajaccio-corse")).toBe("Ajaccio (Corse)€20 pledged · €30 captured");
    // The fund's own id, without "dep-", still finds the stop's name.
    expect(row("la-rochelle")).toBe("La Rochelle€1 pledged");
    // A refund is said; a stop the voyage does not know keeps its id.
    expect(row("atlantis")).toBe("dep-atlantis€5 captured · €5 refunded");
  });

  it("shows cabin legs, projects and the common fund as their own groups", async () => {
    render(tree());
    toggle(true);
    await screen.findByTestId("public-totals-body");
    expect(within(screen.getByTestId("public-totals-legs")).getByRole("heading")).toHaveTextContent("Cabins");
    expect(row("leg-la-rochelle-to-ajaccio-corse")).toBe("La Rochelle → Ajaccio (Corse)€80 captured");
    expect(row("project-p-plastics")).toBe("Plastics Initiative€35 captured · 2 donations");
    expect(row("project-p-unknown")).toBe("p-unknown€9.50 captured · 1 donation");
    expect(screen.getByTestId("public-totals-common-fund").textContent).toBe("Common fundShared boat costs€12 captured");
    expect(screen.getByText("Pledged: authorised, not charged yet. Captured: charged.")).toBeInTheDocument();
  });

  it("opens a stop from its row, and only for a stop the voyage knows", async () => {
    const onSelectStop = vi.fn();
    render(tree({ onSelectStop }));
    toggle(true);
    await screen.findByTestId("public-totals-body");
    fireEvent.click(screen.getByRole("button", { name: "Open Ajaccio (Corse)" }));
    fireEvent.click(screen.getByRole("button", { name: "Open La Rochelle" }));
    expect(onSelectStop.mock.calls).toEqual([["dep-ajaccio-corse"], ["dep-la-rochelle"]]);
    expect(within(screen.getByTestId("public-total-atlantis")).queryByRole("button")).toBeNull();
    // Legs, projects and the common fund are text, not controls.
    expect(within(screen.getByTestId("public-totals-legs")).queryByRole("button")).toBeNull();
  });

  it("has no buttons at all when it cannot open a stop", async () => {
    render(tree());
    toggle(true);
    await screen.findByTestId("public-totals-body");
    expect(within(screen.getByTestId("public-totals-body")).queryByRole("button")).toBeNull();
  });

  it("leaves out a group that has nothing, but always shows the common fund", async () => {
    vi.mocked(fetchPublicFunds).mockResolvedValue({ ...none, stops: [funds.stops[0]] });
    render(tree());
    toggle(true);
    await screen.findByTestId("public-totals-body");
    expect(screen.queryByTestId("public-totals-legs")).toBeNull();
    expect(screen.queryByTestId("public-totals-projects")).toBeNull();
    expect(screen.getByTestId("public-totals-common-fund")).toHaveTextContent("Nothing yet");
  });

  it("says so when there is no pledge at all", async () => {
    vi.mocked(fetchPublicFunds).mockResolvedValue(none);
    render(tree());
    toggle(true);
    expect(await screen.findByTestId("public-totals-empty")).toHaveTextContent("No pledge yet.");
    expect(screen.queryByTestId("public-totals-body")).toBeNull();
  });

  it("says the totals are loading, then that they could not be read", async () => {
    let fail!: (reason: Error) => void;
    vi.mocked(fetchPublicFunds).mockReturnValue(new Promise((_resolve, reject) => { fail = reject; }));
    render(tree());
    toggle(true);
    expect(await screen.findByTestId("public-totals-loading")).toHaveTextContent("Loading totals…");
    await act(async () => fail(new Error("down")));
    expect(screen.getByTestId("public-totals-error")).toHaveTextContent("The totals are not available right now.");
    expect(screen.queryByTestId("public-totals-body")).toBeNull();
  });

  it("reads again after a new pledge while open, and keeps the old figures on screen meanwhile", async () => {
    const view = render(tree({ refreshToken: 0 }));
    toggle(true);
    await screen.findByTestId("public-totals-body");
    expect(fetchPublicFunds).toHaveBeenCalledTimes(1);

    let answer!: (value: PublicFunds) => void;
    vi.mocked(fetchPublicFunds).mockReturnValue(new Promise((resolve) => { answer = resolve; }));
    view.rerender(tree({ refreshToken: 1 }));
    await waitFor(() => expect(fetchPublicFunds).toHaveBeenCalledTimes(2));
    expect(screen.queryByTestId("public-totals-loading")).toBeNull();
    expect(row("la-rochelle")).toBe("La Rochelle€1 pledged");
    await act(async () => answer({ ...funds, stops: [{ ...funds.stops[1], authorized_eur: "21.00" }] }));
    expect(row("la-rochelle")).toBe("La Rochelle€21 pledged");
  });

  it("does not read after a new pledge while closed, and reads on the next opening", async () => {
    const view = render(tree({ refreshToken: 0 }));
    view.rerender(tree({ refreshToken: 1 }));
    expect(fetchPublicFunds).not.toHaveBeenCalled();
    toggle(true);
    await screen.findByTestId("public-totals-body");
    toggle(false);
    toggle(true);
    await waitFor(() => expect(fetchPublicFunds).toHaveBeenCalledTimes(2));
  });

  it("is written in French too", async () => {
    await i18n.changeLanguage("fr");
    render(tree());
    expect(screen.getByRole("heading", { name: "Où va l’argent" })).toBeInTheDocument();
    toggle(true);
    await screen.findByTestId("public-totals-body");
    expect(row("ajaccio-corse").replace(/\s/g, " ")).toBe("Ajaccio (Corse)20 € promis · 30 € encaissés");
    expect(row("project-p-plastics").replace(/\s/g, " ")).toBe("Plastics Initiative35 € encaissés · 2 dons");
    expect(within(screen.getByTestId("public-totals-legs")).getByRole("heading")).toHaveTextContent("Cabines");
    expect(screen.getByText("Promis : autorisé, pas encore débité. Encaissé : débité.")).toBeInTheDocument();
  });
});

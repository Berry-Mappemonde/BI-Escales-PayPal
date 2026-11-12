import { fireEvent, render, screen, within } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import { listPledges, fetchPayPalSubscriptions } from "../api/escales";
import type { PublicPledge } from "../api/types";
import TreasurerStudio from "../components/TreasurerStudio";

vi.mock("../api/escales", () => ({ listPledges: vi.fn(), fetchPayPalSubscriptions: vi.fn() }));
vi.mock("./DashboardGrid", () => ({
  DashboardGrid: ({ rows, label }: { rows: unknown[]; label: string }) =>
    <pre aria-label={label}>{JSON.stringify(rows)}</pre>,
}));

const base = {
  id: "first", status: "captured", intent: "CAPTURE", currency: "EUR", amount_eur: "100.00",
  milestone_id: "dep-brest", description: "private@example.test", contributor: "Private Supporter",
} satisfies PublicPledge;

const dialogPrototype = HTMLDialogElement.prototype;
beforeAll(() => {
  Object.defineProperties(dialogPrototype, {
    showModal: { configurable: true, value(this: HTMLDialogElement) { this.open = true; } },
    close: { configurable: true, value(this: HTMLDialogElement) { this.open = false; } },
  });
});
afterAll(() => {
  Reflect.deleteProperty(dialogPrototype, "showModal");
  Reflect.deleteProperty(dialogPrototype, "close");
});

beforeEach(async () => {
  vi.resetAllMocks();
  await i18n.changeLanguage("en");
  vi.mocked(listPledges).mockResolvedValue([
    base,
    { ...base, id: "second", currency: "USD", amount_eur: "30.00" },
    { ...base, id: "third", status: "authorized", amount_eur: "20.00", milestone_id: "dep-lorient" },
  ]);
  vi.mocked(fetchPayPalSubscriptions).mockResolvedValue({
    items: [{ subscription_id: "test-sub", status: "ACTIVE", subscriber_email: "crew@example.test" }],
  });
});

function open(demo: boolean) {
  return render(
    <I18nextProvider i18n={i18n}>
      <TreasurerStudio adminKey="test-key" demo={demo}
        stopNames={{ "dep-brest": "Brest", "dep-lorient": "Lorient" }} onClose={vi.fn()} />
    </I18nextProvider>,
  );
}

describe("treasurer dashboard", () => {
  it("never sends a key or loads Crew records in demo mode and strips private pledge fields", async () => {
    open(true);
    const dialog = screen.getByRole("dialog");
    await within(dialog).findByText("Funding by destination");
    expect(listPledges).toHaveBeenCalledWith("", { demoTreasurer: true });
    expect(dialog.textContent).not.toMatch(/private@example.test|Private Supporter/);
    fireEvent.click(within(dialog).getByRole("button", { name: "Crew memberships" }));
    expect(within(dialog).getByText("Membership records are available with treasurer access.")).toBeInTheDocument();
    expect(fetchPayPalSubscriptions).not.toHaveBeenCalled();
  });

  it("filters totals and groups within the selected currency", async () => {
    open(false);
    const dialog = screen.getByRole("dialog");
    await within(dialog).findByText("€100.00");
    expect(within(dialog).getByText("€20.00")).toBeInTheDocument();
    fireEvent.change(within(dialog).getByLabelText("Status"), { target: { value: "authorized" } });
    expect(within(dialog).queryByText("€100.00")).not.toBeInTheDocument();
    expect(within(dialog).getByLabelText("Pledges", { selector: "pre" })).toHaveTextContent("Lorient");
    fireEvent.click(within(dialog).getByRole("button", { name: "Clear filters" }));
    fireEvent.change(within(dialog).getByLabelText("Currency"), { target: { value: "USD" } });
    expect(within(dialog).getByText("$30.00")).toBeInTheDocument();
    fireEvent.change(within(dialog).getByLabelText("Group by"), { target: { value: "status" } });
    expect(within(dialog).getByLabelText("Pledges", { selector: "pre" })).toHaveTextContent('"label":"Captured"');
  });

  it("loads Crew only after opening its keyed view", async () => {
    open(false);
    const dialog = screen.getByRole("dialog");
    await within(dialog).findByText("Funding by destination");
    expect(listPledges).toHaveBeenCalledWith("test-key", undefined);
    expect(fetchPayPalSubscriptions).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Crew memberships" }));
    const grid = await within(dialog).findByLabelText("Crew memberships", { selector: "pre" });
    expect(grid).toHaveTextContent("crew@example.test");
    expect(fetchPayPalSubscriptions).toHaveBeenCalledWith("test-key");
  });

  it("keeps the dashboard data behind successful treasurer access and can retry", async () => {
    vi.mocked(listPledges).mockRejectedValueOnce(new Error("Forbidden"));
    open(false);
    const dialog = screen.getByRole("dialog");
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Check your treasurer access");
    expect(within(dialog).queryByRole("button", { name: "Crew memberships" })).not.toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Refresh data" }));
    expect(await within(dialog).findByText("Funding by destination")).toBeInTheDocument();
  });
});

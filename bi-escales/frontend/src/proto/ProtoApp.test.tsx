import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { pledgeStates } from "./mock";
import { ProtoApp } from "./ProtoApp";
import { en, fr } from "./strings";

function open(query: string) {
  window.history.replaceState(null, "", `/src/proto/index.html?${query}`);
  render(<ProtoApp />);
}

function keyPaths(value: object, prefix = ""): string[] {
  return Object.entries(value).flatMap(([key, child]) =>
    typeof child === "object" ? keyPaths(child, `${prefix}${key}.`) : [`${prefix}${key}`],
  );
}

describe("proto preview", () => {
  const fetchSpy = vi.fn();

  beforeEach(() => {
    fetchSpy.mockClear();
    vi.stubGlobal("fetch", fetchSpy);
  });

  afterEach(() => {
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(document.querySelector('script[src*="paypal"]')).toBeNull();
    expect("paypal" in window).toBe(false);
    cleanup();
    vi.unstubAllGlobals();
  });

  it("keeps FR and EN strings in step", () => {
    expect(keyPaths(fr)).toEqual(keyPaths(en));
  });

  it("shows the Ajaccio stop with status, rows, logbook and next step", () => {
    open("screen=stop&lang=en");
    expect(screen.getByRole("heading", { name: "Ajaccio" })).toBeInTheDocument();
    expect(screen.getByText("En route")).toBeInTheDocument();
    expect(screen.getByText("18 Nov, logbook ETA")).toBeInTheDocument();
    expect(screen.getByText("22 Nov, planned")).toBeInTheDocument();
    expect(screen.getByText("Weather stop at Cartagena. ETA 18 Nov at Ajaccio.")).toBeInTheDocument();
    expect(screen.getByText("Held by PayPal, not charged")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Back this leg" })).toBeInTheDocument();
  });

  it("backs and un-backs the leg locally, keeping focus on the action", () => {
    open("screen=stop&lang=en");
    fireEvent.click(screen.getByRole("button", { name: "Back this leg" }));
    expect(screen.getByText("You are backing this leg")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Undo" })).toHaveFocus();
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(screen.getByRole("button", { name: "Back this leg" })).toHaveFocus();
  });

  it("switches language in place and updates the document", async () => {
    open("screen=stop&lang=en");
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "FR" }));
    });
    expect(screen.getByText("Retenu par PayPal, non débité")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Soutenir cette étape" })).toBeInTheDocument();
    expect(document.documentElement.lang).toBe("fr");
    expect(window.location.search).toContain("lang=fr");
  });

  it("never leaves a doubled full stop after a French date", () => {
    open("screen=stop&lang=fr");
    expect(document.body.textContent).not.toContain("..");
  });

  it("links each citation to its source row", () => {
    open("screen=captain&lang=en");
    expect(screen.getByText("Wait")).toBeInTheDocument();
    expect(screen.getByText("7AG23904…")).toBeInTheDocument();
    expect(screen.getByText("valid to 3 Dec")).toBeInTheDocument();
    const orders = screen.getByText("orders.get").closest("li") as HTMLElement;
    expect(within(orders).getByText("approved")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Source 2: authorizations.get" }));
    const row = screen.getByText("authorizations.get").closest("li");
    expect(row).toHaveFocus();
    expect(row).toHaveAttribute("data-active");
  });

  it("approves the proposal, and undo restores the choice", () => {
    open("screen=captain&lang=en");
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(screen.getByRole("status")).toHaveTextContent("No money moved");
    expect(screen.queryByRole("button", { name: "Override" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(screen.getByRole("button", { name: "Approve" })).toHaveFocus();
  });

  it("overrides with a named replacement, and can back out", () => {
    open("screen=captain&lang=en");
    fireEvent.click(screen.getByRole("button", { name: "Override" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    fireEvent.click(screen.getByRole("button", { name: "Override" }));
    fireEvent.click(screen.getByRole("button", { name: "Release the hold" }));
    expect(screen.getByRole("status")).toHaveTextContent("release the hold");
  });

  it("gives every pledge state its own glyph and a label", () => {
    open("screen=pledges&lang=en");
    const glyphs = pledgeStates.map(({ id }) => {
      const row = within(screen.getByTestId(`pledge-${id}`));
      expect(row.getByText(en.status[id])).toBeInTheDocument();
      return screen.getByTestId(`pledge-${id}`).querySelector("svg")?.innerHTML;
    });
    expect(new Set(glyphs).size).toBe(pledgeStates.length);
  });

  it("moves between screens with the arrow keys", () => {
    open("screen=stop&lang=en");
    fireEvent.keyDown(screen.getByRole("tab", { name: "Stop" }), { key: "ArrowLeft" });
    expect(screen.getByRole("tab", { name: "Pledges" })).toHaveFocus();
    expect(screen.getByRole("tab", { name: "Pledges" })).toHaveAttribute("aria-selected", "true");
    expect(window.location.search).toContain("screen=pledges");
  });
});

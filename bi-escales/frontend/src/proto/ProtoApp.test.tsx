import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { pledgeStates } from "./mock";
import protoCss from "./proto.css?raw";
import statusChipSource from "./StatusChip.tsx?raw";
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
    vi.useRealTimers();
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

  it("lets Override release the hold and nothing else", () => {
    open("screen=captain&lang=en");
    fireEvent.click(screen.getByRole("button", { name: "Override" }));
    expect(screen.getByText(/Captured on arrival \(on departure for cabins\), only after a person approves\./)).toBeInTheDocument();
    const decision = screen.getByRole("button", { name: "Release the hold" }).parentElement as HTMLElement;
    expect(within(decision).getAllByRole("button").map((button) => button.textContent)).toEqual([
      "Release the hold",
      "Cancel",
    ]);
    expect(screen.queryByRole("button", { name: /capture/i })).toBeNull();
  });

  it("offers no capture action in French either", () => {
    open("screen=captain&lang=fr");
    fireEvent.click(screen.getByRole("button", { name: "Passer outre" }));
    expect(screen.getByRole("button", { name: "Libérer la retenue" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /encaiss/i })).toBeNull();
  });

  it("can back out of Override before starting a release", () => {
    open("screen=captain&lang=en");
    fireEvent.click(screen.getByRole("button", { name: "Override" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByRole("button", { name: "Approve" })).toHaveFocus();
  });

  describe("release undo window", () => {
    const wait = (ms: number) => act(() => void vi.advanceTimersByTime(ms));

    function startRelease() {
      vi.useFakeTimers();
      open("screen=captain&lang=en");
      fireEvent.click(screen.getByRole("button", { name: "Override" }));
      fireEvent.click(screen.getByRole("button", { name: "Release the hold" }));
    }

    it("counts down from 5 s with Undo available", () => {
      startRelease();
      expect(screen.getByText("Releasing the hold in 5 s")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Undo" })).toHaveFocus();
      wait(1000);
      expect(screen.getByText("Releasing the hold in 4 s")).toBeInTheDocument();
      wait(3000);
      expect(screen.getByText("Releasing the hold in 1 s")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Undo" })).toBeInTheDocument();
    });

    it("announces once rather than every second", () => {
      startRelease();
      const announced = screen.getByRole("status").textContent;
      expect(announced).toContain("5 seconds");
      wait(2000);
      expect(screen.getByRole("status").textContent).toBe(announced);
    });

    it("is final after 5 s: Undo goes and no decision can be made", () => {
      startRelease();
      wait(5000);
      expect(screen.getByRole("status")).toHaveTextContent("Hold released. This is final.");
      expect(screen.queryByRole("button", { name: "Undo" })).toBeNull();
      expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
      expect(screen.queryByRole("button", { name: "Override" })).toBeNull();
      expect(screen.getByRole("status").closest("section")).toHaveFocus();
    });

    it("undo cancels the release for good", () => {
      startRelease();
      wait(3000);
      fireEvent.click(screen.getByRole("button", { name: "Undo" }));
      wait(10000);
      expect(screen.getByRole("status")).toBeEmptyDOMElement();
      expect(screen.getByRole("button", { name: "Approve" })).toHaveFocus();
    });

    it("keeps counting on another tab and stays final on return", () => {
      startRelease();
      fireEvent.click(screen.getByRole("tab", { name: "Stop" }));
      wait(5000);
      fireEvent.click(screen.getByRole("tab", { name: "Captain" }));
      expect(screen.getByRole("status")).toHaveTextContent("This is final.");
      expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
    });
  });

  it("keeps amber for money held: En route has its own colour and glyph", () => {
    open("screen=stop&lang=en");
    const chip = screen.getByText("En route");
    expect(chip.style.getPropertyValue("--st")).toBe("var(--color-st-route)");

    const held = screen.getByTestId("pledge-held");
    expect(held.querySelector("[style]")?.getAttribute("style")).toContain("--color-st-progress");
    expect(chip.querySelector("svg")?.innerHTML).not.toBe(held.querySelector("svg")?.innerHTML);

    expect(statusChipSource.match(/--color-st-progress/g)).toHaveLength(1);
    expect(protoCss).not.toContain("--color-st-progress");
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

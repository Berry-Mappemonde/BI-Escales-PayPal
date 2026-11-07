import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PayPalErrorBoundary } from "./PayPalErrorBoundary";

function Boom(): never {
  throw new TypeError("W.render is not a function");
}

describe("PayPalErrorBoundary", () => {
  it("contains a PayPal widget crash and keeps siblings rendered", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    render(
      <div>
        <p>map still here</p>
        <PayPalErrorBoundary testId="pp-err">
          <Boom />
        </PayPalErrorBoundary>
      </div>,
    );
    expect(screen.getByText("map still here")).toBeInTheDocument();
    expect(screen.getByTestId("pp-err")).toBeInTheDocument();
    spy.mockRestore();
    warn.mockRestore();
  });
});

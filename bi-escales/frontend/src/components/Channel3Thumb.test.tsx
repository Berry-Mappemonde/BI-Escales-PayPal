import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Channel3Thumb } from "./Channel3Thumb";

describe("Channel3Thumb", () => {
  it("renders the picture with the item title as alt text, lazily, in a fixed box", () => {
    render(<Channel3Thumb src="https://img.example.test/dive.jpg" title="Dive computer" />);
    const photo = screen.getByRole("img", { name: "Dive computer" });
    expect(photo).toHaveAttribute("src", "https://img.example.test/dive.jpg");
    expect(photo).toHaveAttribute("loading", "lazy");
    expect(photo).toHaveAttribute("decoding", "async");
    // Width and height are on the element, so the layout is reserved before the picture loads.
    expect(photo).toHaveAttribute("width", "48");
    expect(photo).toHaveAttribute("height", "48");
    expect(photo).toHaveClass("channel3-thumb", "channel3-thumb--md");
  });

  it.each([
    ["sm", "32"],
    ["md", "48"],
    ["lg", "64"],
  ] as const)("has one square per size: %s is %spx", (size, edge) => {
    render(<Channel3Thumb src="https://img.example.test/a.jpg" title="A" size={size} />);
    const photo = screen.getByRole("img");
    expect(photo).toHaveAttribute("width", edge);
    expect(photo).toHaveAttribute("height", edge);
  });

  it.each([undefined, null, "", "   "])("renders nothing, not even a placeholder, when the URL is %j", (src) => {
    const { container } = render(<Channel3Thumb src={src} title="Dive computer" />);
    expect(container).toBeEmptyDOMElement();
  });

  it.each(["javascript:alert(1)", "data:image/png;base64,AAAA", "ftp://host/a.png", "not a url"])(
    "treats %j as no picture",
    (src) => {
      const { container } = render(<Channel3Thumb src={src} title="Dive computer" />);
      expect(container).toBeEmptyDOMElement();
    },
  );

  it("keeps the caller's class and test id", () => {
    render(<Channel3Thumb src="https://img.example.test/a.jpg" title="A" className="wishlist-item-image" testId="wishlist-item-image" />);
    expect(screen.getByTestId("wishlist-item-image")).toHaveClass("channel3-thumb", "wishlist-item-image");
  });
});

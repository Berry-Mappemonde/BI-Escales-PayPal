import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import { MapLayerControl } from "./MapLayerControl";

function show(layers = { projects: true, marinas: true }, onToggle = vi.fn()) {
  render(
    <I18nextProvider i18n={i18n}>
      <MapLayerControl layers={layers} onToggle={onToggle} />
    </I18nextProvider>,
  );
  return onToggle;
}

describe("MapLayerControl", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
  });

  it("is a named group of two toggles, Projects then Marinas", () => {
    show();
    const group = screen.getByRole("group", { name: "Map layers" });
    const toggles = within(group).getAllByRole("button");
    expect(toggles.map((button) => button.textContent)).toEqual(["Projects", "Marinas"]);
  });

  it("reports each layer's state with aria-pressed", () => {
    show({ projects: true, marinas: false });
    expect(screen.getByRole("button", { name: "Projects" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Marinas" })).toHaveAttribute("aria-pressed", "false");
  });

  it("asks to toggle the layer that was pressed", () => {
    const onToggle = show();
    fireEvent.click(screen.getByRole("button", { name: "Marinas" }));
    fireEvent.click(screen.getByRole("button", { name: "Projects" }));
    expect(onToggle.mock.calls).toEqual([["marinas"], ["projects"]]);
  });

  it("is labelled in French", async () => {
    show();
    await act(async () => {
      await i18n.changeLanguage("fr");
    });
    expect(screen.getByRole("group", { name: "Couches de la carte" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Projets" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Marinas" })).toBeInTheDocument();
  });
});

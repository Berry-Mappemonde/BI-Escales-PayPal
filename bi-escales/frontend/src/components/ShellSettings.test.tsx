/** B13: app settings (language, theme) are one group, outside the visitor and the treasurer tools. */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import { ShellSettings } from "./ShellSettings";

function show(props: Partial<React.ComponentProps<typeof ShellSettings>> = {}) {
  const onToggleTheme = vi.fn();
  render(
    <I18nextProvider i18n={i18n}>
      <ShellSettings theme="dark" onToggleTheme={onToggleTheme} {...props} />
    </I18nextProvider>,
  );
  return onToggleTheme;
}

describe("ShellSettings", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
  });
  afterEach(async () => {
    localStorage.removeItem("bi-escales-lang");
    await i18n.changeLanguage("en");
  });

  it("is one group named Settings, holding the language and the theme and nothing else", () => {
    show();
    const group = screen.getByRole("group", { name: "Settings" });
    expect(group).toHaveAttribute("data-testid", "shell-settings");
    expect(within(group).getByRole("group", { name: "Language" })).toBeInTheDocument();
    expect(within(group).getAllByRole("button")).toHaveLength(3);
    expect(group.querySelectorAll("a, input, select, textarea")).toHaveLength(0);
  });

  it("marks the current language and switches it, for the whole app", async () => {
    show();
    const fr = screen.getByRole("button", { name: i18n.t("app.langFrSwitch") });
    const en = screen.getByRole("button", { name: i18n.t("app.langEnSwitch") });
    expect(en).toHaveAttribute("aria-pressed", "true");
    expect(fr).toHaveAttribute("aria-pressed", "false");

    fireEvent.click(fr);
    expect(i18n.language).toBe("fr");
    expect(localStorage.getItem("bi-escales-lang")).toBe("fr");
    expect(document.documentElement.lang).toBe("fr");
    // The group's own name follows the language.
    expect(await screen.findByRole("group", { name: "Réglages" })).toBeInTheDocument();
  });

  it("offers the other theme and asks the app to switch", () => {
    const onToggleTheme = show({ theme: "dark" });
    const toggle = screen.getByTestId("theme-toggle");
    expect(toggle).toHaveAccessibleName("Light");
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(toggle);
    expect(onToggleTheme).toHaveBeenCalledTimes(1);
  });

  it("names the dark theme when the light one is on", () => {
    show({ theme: "light" });
    expect(screen.getByTestId("theme-toggle")).toHaveAccessibleName("Dark");
    expect(screen.getByTestId("theme-toggle")).toHaveAttribute("aria-pressed", "true");
  });

  it("keeps the rail's test ids, and gives the treasurer page copy its own", () => {
    show({ place: "treasurer-page" });
    expect(screen.queryByTestId("theme-toggle")).toBeNull();
    expect(screen.getByTestId("treasurer-page-shell-settings")).toBeInTheDocument();
    expect(screen.getByTestId("treasurer-page-theme-toggle")).toBeInTheDocument();
  });
});

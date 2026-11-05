import { fireEvent, render, screen } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import { BiShellApp } from "./BiShellApp";

vi.mock("leaflet", () => {
  const map = {
    remove: vi.fn(),
    invalidateSize: vi.fn(),
  };
  return {
    default: {
      map: vi.fn(() => map),
      tileLayer: vi.fn(() => ({ addTo: vi.fn() })),
      layerGroup: vi.fn(() => ({ addTo: vi.fn() })),
      circleMarker: vi.fn(() => ({ addTo: vi.fn() })),
    },
  };
});

describe("BiShellApp empty shell", () => {
  it("renders header, left slots, map stage, and gear settings", async () => {
    await i18n.changeLanguage("en");
    render(
      <I18nextProvider i18n={i18n}>
        <BiShellApp />
      </I18nextProvider>,
    );
    expect(screen.getByTestId("bi-shell")).toBeInTheDocument();
    expect(screen.getByTestId("bi-shell-header")).toBeInTheDocument();
    expect(screen.getByTestId("bi-slot-left.marinas")).toBeInTheDocument();
    expect(screen.getByTestId("bi-shell-settings-toggle")).toBeInTheDocument();
    expect(screen.getByTestId("bi-shell-map")).toBeInTheDocument();
  });

  it("opens Console tab as Treasurer mount point", async () => {
    await i18n.changeLanguage("en");
    render(
      <I18nextProvider i18n={i18n}>
        <BiShellApp />
      </I18nextProvider>,
    );
    fireEvent.click(screen.getByTestId("bi-shell-view-console"));
    expect(screen.getByTestId("bi-shell-console")).toBeInTheDocument();
  });
});

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { I18nextProvider } from "react-i18next";
import i18n from "../i18n";
import { MaskedSecretInput } from "./MaskedSecretInput";

describe("MaskedSecretInput", () => {
  it("masks by default and toggles visibility without logging the value", () => {
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const onChange = vi.fn();
    render(
      <I18nextProvider i18n={i18n}>
        <MaskedSecretInput label="Key" value="top-secret" onChange={onChange} testId="secret-field" />
      </I18nextProvider>,
    );
    const input = screen.getByTestId("secret-field");
    expect(input).toHaveAttribute("type", "password");
    expect(input).toHaveAttribute("autocomplete", "off");
    fireEvent.click(screen.getByTestId("secret-field-visibility-toggle"));
    expect(input).toHaveAttribute("type", "text");
    expect(logSpy).not.toHaveBeenCalled();
    logSpy.mockRestore();
  });
});

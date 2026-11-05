import { fireEvent, render, screen } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { afterEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import fr from "../i18n/locales/fr.json";

const imported = vi.hoisted(() => ({ count: 0, fail: false }));

vi.mock("./TreasurerStudio", () => {
  imported.count += 1;
  return {
    default: ({ onClose }: { onClose: () => void }) => {
      if (imported.fail) throw new Error("Studio failed");
      return (
        <button type="button" data-testid="studio-stub" onClick={onClose}>
          stub
        </button>
      );
    },
  };
});

async function renderSection() {
  const { TreasurerStudioSection } = await import("./TreasurerStudioSection");
  return render(
    <I18nextProvider i18n={i18n}>
      <TreasurerStudioSection pledges={[]} />
    </I18nextProvider>,
  );
}

afterEach(() => {
  vi.unstubAllEnvs();
  vi.resetModules();
  imported.count = 0;
  imported.fail = false;
});

describe("TreasurerStudioSection", () => {
  it.each([undefined, "", "0"])("ne rend rien et n’importe rien avec le drapeau à %j", async (flag) => {
    if (flag !== undefined) vi.stubEnv("VITE_ENABLE_AG_STUDIO", flag);
    const { container } = await renderSection();
    expect(container).toBeEmptyDOMElement();
    expect(imported.count).toBe(0);
  });

  it("n’importe Studio qu’au clic, puis se ferme", async () => {
    vi.stubEnv("VITE_ENABLE_AG_STUDIO", "1");
    await renderSection();
    expect(imported.count).toBe(0);

    fireEvent.click(screen.getByTestId("treasurer-studio-open"));
    fireEvent.click(await screen.findByTestId("studio-stub"));

    expect(imported.count).toBe(1);
    expect(screen.queryByTestId("studio-stub")).not.toBeInTheDocument();
    expect(screen.getByTestId("treasurer-studio-open")).toHaveFocus();
  });

  it("garde l’app en vie si Studio échoue", async () => {
    vi.stubEnv("VITE_ENABLE_AG_STUDIO", "1");
    imported.fail = true;
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    await i18n.changeLanguage("fr");
    await renderSection();

    fireEvent.click(screen.getByTestId("treasurer-studio-open"));

    expect(await screen.findByText(fr.studio.loadError)).toBeInTheDocument();
    expect(screen.getByTestId("treasurer-studio-open")).toBeInTheDocument();
    warn.mockRestore();
    error.mockRestore();
  });
});

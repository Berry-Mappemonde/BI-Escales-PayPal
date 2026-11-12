import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as escalesApi from "../api/escales";
import i18n, { setLanguage } from "../i18n";
import { buildPublicWishlist } from "./fixtures";
import { WishlistsPage } from "./WishlistsPage";

vi.mock("../components/PledgeButton", () => ({
  PledgeButton: ({ values }: { values: { contributor?: string } }) => (
    <div data-testid="pledge-button" data-contributor={values.contributor ?? ""} />
  ),
}));

const toggleTheme = vi.fn();
vi.mock("../hooks/useTheme", () => ({
  useTheme: () => ({ theme: "dark", toggleTheme }),
}));

async function renderPage(items = 2) {
  vi.spyOn(escalesApi, "fetchFeatures").mockResolvedValue({ wishlists: true });
  vi.spyOn(escalesApi, "fetchPublicWishlists").mockResolvedValue({
    wishlists: [buildPublicWishlist(items)],
  });
  render(<WishlistsPage />);
  await waitFor(() => {
    expect(screen.getAllByTestId("wishlist-item-card")).toHaveLength(items);
  });
}

describe("WishlistsPage header", () => {
  afterEach(async () => {
    vi.restoreAllMocks();
    toggleTheme.mockClear();
    await setLanguage("en");
  });

  it("uses the shared settings control and a plain link back to the map", async () => {
    await setLanguage("en");
    await renderPage();
    const settings = screen.getByTestId("wishlists-shell-settings");
    expect(within(settings).getByText("FR")).toHaveAttribute("aria-pressed", "false");
    expect(within(settings).getByText("EN")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("wishlists-back-map")).toHaveAttribute("href", "/");
    expect(screen.getByTestId("wishlists-back-map")).toHaveTextContent("Back to map");
  });

  it("switches the page language from the header", async () => {
    await setLanguage("en");
    await renderPage();
    const settings = screen.getByTestId("wishlists-shell-settings");
    fireEvent.click(within(settings).getByText("FR"));
    await waitFor(() => expect(i18n.language).toBe("fr"));
    expect(screen.getByTestId("wishlists-back-map")).toHaveTextContent("Retour à la carte");
    expect(screen.getAllByTestId("wishlist-line-target")[0]).toHaveTextContent(/^Objectif\s: /);
  });

  it("toggles the theme from the header", async () => {
    await renderPage();
    fireEvent.click(screen.getByTestId("wishlists-theme-toggle"));
    expect(toggleTheme).toHaveBeenCalledTimes(1);
  });

  it("labels the name field and says what the target is", async () => {
    await setLanguage("en");
    await renderPage();
    expect(screen.getByLabelText("Your name, for every gift on this page (optional)")).toBe(
      screen.getByTestId("wishlists-contributor"),
    );
    expect(screen.getAllByTestId("wishlist-line-target")[0]).toHaveTextContent(/^Target: /);
  });

  it("sends the page's name with every gift, unless a card has its own", async () => {
    await renderPage(2);
    fireEvent.change(screen.getByTestId("wishlists-contributor"), { target: { value: "Ada" } });
    const names = () => screen.getAllByTestId("wishlist-fund-contributor") as HTMLInputElement[];
    expect(names().map((input) => input.value)).toEqual(["Ada", "Ada"]);
    expect(screen.getAllByTestId("pledge-button").map((b) => b.getAttribute("data-contributor"))).toEqual([
      "Ada",
      "Ada",
    ]);

    fireEvent.change(names()[0], { target: { value: "Grace" } });
    fireEvent.change(screen.getByTestId("wishlists-contributor"), { target: { value: "Ada L." } });
    expect(names().map((input) => input.value)).toEqual(["Grace", "Ada L."]);
    expect(screen.getAllByTestId("pledge-button").map((b) => b.getAttribute("data-contributor"))).toEqual([
      "Grace",
      "Ada L.",
    ]);
  });
});

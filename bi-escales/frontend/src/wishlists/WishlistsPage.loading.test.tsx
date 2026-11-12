/** A12: while the wishlists load, the page shows the outline of the cards, not an empty sheet. */
import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as escalesApi from "../api/escales";
import type { PublicPledge } from "../api/types";
import { buildPublicWishlist } from "./fixtures";
import { WishlistsPage } from "./WishlistsPage";

const pledged: { onAuthorized?: (pledge: PublicPledge) => void } = {};
vi.mock("./WishlistItemCard", () => ({
  WishlistItemCard: ({ onAuthorized }: { onAuthorized: (pledge: PublicPledge) => void }) => {
    pledged.onAuthorized = onAuthorized;
    return <article data-testid="wishlist-item-card" />;
  },
}));
vi.mock("../hooks/useTheme", () => ({ useTheme: () => ({ theme: "dark", toggleTheme: vi.fn() }) }));

type Lists = Awaited<ReturnType<typeof escalesApi.fetchPublicWishlists>>;

describe("WishlistsPage while loading", () => {
  afterEach(() => vi.restoreAllMocks());

  it("shows placeholder cards and a status line until the lists arrive", async () => {
    let answer!: (value: Lists) => void;
    vi.spyOn(escalesApi, "fetchFeatures").mockResolvedValue({ wishlists: true });
    vi.spyOn(escalesApi, "fetchPublicWishlists").mockReturnValue(new Promise((resolve) => { answer = resolve; }));
    render(<WishlistsPage />);

    const skeleton = screen.getByTestId("wishlists-skeleton");
    expect(skeleton.children).toHaveLength(8);
    // Decoration: hidden from assistive technology, which gets the status line instead.
    expect(skeleton).toHaveAttribute("aria-hidden", "true");
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.queryByTestId("wishlist-item-card")).toBeNull();

    await act(async () => answer({ wishlists: [buildPublicWishlist(3)] }));
    await waitFor(() => expect(screen.getAllByTestId("wishlist-item-card")).toHaveLength(3));
    expect(screen.queryByTestId("wishlists-skeleton")).toBeNull();
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("is already there while the features answer is on its way", () => {
    vi.spyOn(escalesApi, "fetchFeatures").mockReturnValue(new Promise(() => {}));
    const lists = vi.spyOn(escalesApi, "fetchPublicWishlists");
    render(<WishlistsPage />);
    expect(screen.getByTestId("wishlists-skeleton")).toBeInTheDocument();
    expect(lists).not.toHaveBeenCalled();
  });

  it("gives way to the notice when wishlists are switched off", async () => {
    vi.spyOn(escalesApi, "fetchFeatures").mockResolvedValue({ wishlists: false });
    render(<WishlistsPage />);
    await waitFor(() => expect(screen.queryByTestId("wishlists-skeleton")).toBeNull());
    expect(screen.getByText(/not enabled|ne sont pas activées/i)).toBeInTheDocument();
  });

  it("gives way to the error when the lists cannot be read", async () => {
    vi.spyOn(escalesApi, "fetchFeatures").mockResolvedValue({ wishlists: true });
    vi.spyOn(escalesApi, "fetchPublicWishlists").mockRejectedValue(new Error("wishlists down"));
    render(<WishlistsPage />);
    expect(await screen.findByText("wishlists down")).toBeInTheDocument();
    expect(screen.queryByTestId("wishlists-skeleton")).toBeNull();
  });

  it("keeps the lists on screen, without placeholders, while it reloads after a pledge", async () => {
    vi.spyOn(escalesApi, "fetchFeatures").mockResolvedValue({ wishlists: true });
    const lists = vi.spyOn(escalesApi, "fetchPublicWishlists").mockResolvedValue({ wishlists: [buildPublicWishlist(2)] });
    render(<WishlistsPage />);
    await waitFor(() => expect(screen.getAllByTestId("wishlist-item-card")).toHaveLength(2));

    lists.mockReturnValue(new Promise(() => {}));
    await act(async () => pledged.onAuthorized?.({ id: "p-1" } as PublicPledge));
    await waitFor(() => expect(lists).toHaveBeenCalledTimes(2));
    expect(screen.getAllByTestId("wishlist-item-card")).toHaveLength(2);
    expect(screen.queryByTestId("wishlists-skeleton")).toBeNull();
    expect(screen.getByRole("status")).toBeInTheDocument();
  });
});

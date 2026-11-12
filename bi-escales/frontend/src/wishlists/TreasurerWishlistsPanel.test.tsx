import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi, beforeEach } from "vitest";
import * as escalesApi from "../api/escales";
import type { TreasurerWishlistDoc } from "../api/types";
import i18n from "../i18n";
import { fixtureCatalogEur, fixtureTreasurerWishlist } from "./fixtures";
import { TreasurerWishlistsPanel } from "./TreasurerWishlistsPanel";

describe("TreasurerWishlistsPanel", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("creates a wishlist via POST /treasurer/wishlists", async () => {
    const user = userEvent.setup();
    const create = vi.spyOn(escalesApi, "createTreasurerWishlist").mockResolvedValue({
      _id: "wid-new",
      title: "New",
      slug: "new-slug",
      published: false,
      items: [],
    });
    vi.spyOn(escalesApi, "fetchChannel3Catalog").mockResolvedValue({ item_count: 0, items: [] });
    vi.spyOn(escalesApi, "fetchTreasurerWishlists").mockResolvedValue({ wishlists: [] });
    render(<TreasurerWishlistsPanel adminKey="test-key" />);
    await user.type(screen.getByTestId("wishlist-create-title"), "New");
    await user.type(screen.getByTestId("wishlist-create-slug"), "new-slug");
    await user.click(screen.getByTestId("wishlist-create-submit"));
    await waitFor(() =>
      expect(create).toHaveBeenCalledWith("test-key", { title: "New", slug: "new-slug", items: [] }),
    );
  });

  it("adds, removes, and publishes on an existing list", async () => {
    const user = userEvent.setup();
    vi.spyOn(escalesApi, "fetchChannel3Catalog").mockResolvedValue({
      item_count: 1,
      items: [fixtureCatalogEur],
    });
    vi.spyOn(escalesApi, "fetchTreasurerWishlists").mockResolvedValue({ wishlists: [fixtureTreasurerWishlist] });
    const add = vi.spyOn(escalesApi, "addTreasurerWishlistItem").mockResolvedValue(fixtureTreasurerWishlist);
    const remove = vi.spyOn(escalesApi, "removeTreasurerWishlistItem").mockResolvedValue({
      ...fixtureTreasurerWishlist,
      items: [],
    });
    const publish = vi
      .spyOn(escalesApi, "publishTreasurerWishlist")
      .mockResolvedValueOnce({ ...fixtureTreasurerWishlist, published: true })
      .mockResolvedValueOnce({ ...fixtureTreasurerWishlist, published: false });

    render(<TreasurerWishlistsPanel adminKey="test-key" />);
    await waitFor(() => expect(screen.getByTestId("wishlist-treasurer-select")).toBeInTheDocument());

    await user.selectOptions(screen.getByTestId("wishlist-catalog-pick"), fixtureCatalogEur.channel3_product_id);
    await user.click(screen.getByTestId("wishlist-add-submit"));
    await waitFor(() => expect(add).toHaveBeenCalled());

    await user.click(screen.getByTestId(`wishlist-remove-${fixtureCatalogEur.channel3_product_id}`));
    await waitFor(() => expect(remove).toHaveBeenCalled());

    await user.click(screen.getByTestId("wishlist-publish"));
    await waitFor(() => expect(publish).toHaveBeenCalledWith("test-key", fixtureTreasurerWishlist._id, true));

    await user.click(screen.getByTestId("wishlist-unpublish"));
    await waitFor(() =>
      expect(publish).toHaveBeenLastCalledWith("test-key", fixtureTreasurerWishlist._id, false),
    );
  });

  it("shows each line's picture beside its name, and none for an item without one", async () => {
    vi.spyOn(escalesApi, "fetchChannel3Catalog").mockResolvedValue({ item_count: 1, items: [fixtureCatalogEur] });
    vi.spyOn(escalesApi, "fetchTreasurerWishlists").mockResolvedValue({ wishlists: [fixtureTreasurerWishlist] });
    const { unmount } = render(<TreasurerWishlistsPanel adminKey="test-key" />);
    const line = await screen.findByTestId("treasurer-wishlist-line");
    const photo = screen.getByTestId("treasurer-wishlist-photo");
    expect(line.parentElement).toContainElement(photo);
    expect(photo).toHaveAttribute("src", fixtureCatalogEur.image_url);
    expect(photo).toHaveAttribute("alt", fixtureCatalogEur.name);
    expect(photo).toHaveAttribute("loading", "lazy");
    expect(photo).toHaveAttribute("width", "32");
    unmount();

    vi.spyOn(escalesApi, "fetchChannel3Catalog").mockResolvedValue({
      item_count: 1,
      items: [{ ...fixtureCatalogEur, image_url: null }],
    });
    render(<TreasurerWishlistsPanel adminKey="test-key" />);
    await screen.findByTestId("treasurer-wishlist-line");
    expect(screen.queryByTestId("treasurer-wishlist-photo")).toBeNull();
  });

  it("shows unavailable line when catalogue lacks a stored product id", async () => {
    vi.spyOn(escalesApi, "fetchChannel3Catalog").mockResolvedValue({ item_count: 1, items: [fixtureCatalogEur] });
    vi.spyOn(escalesApi, "fetchTreasurerWishlists").mockResolvedValue({ wishlists: [fixtureTreasurerWishlist] });
    render(<TreasurerWishlistsPanel adminKey="test-key" />);
    await waitFor(() => {
      expect(screen.getByTestId("wishlist-item-unavailable")).toBeInTheDocument();
    });
  });
});

describe("TreasurerWishlistsPanel, usable by a treasurer (brief B11)", () => {
  const personal = { ...fixtureCatalogEur, channel3_product_id: "vest-1", name: "Life vest", quantity_needed: 6 };
  const boat = { ...fixtureCatalogEur, channel3_product_id: "radio-1", name: "VHF radio", quantity_needed: 1 };

  function mockLists(lists: TreasurerWishlistDoc[]) {
    vi.spyOn(escalesApi, "fetchChannel3Catalog").mockResolvedValue({ item_count: 2, items: [personal, boat] });
    vi.spyOn(escalesApi, "fetchTreasurerWishlists").mockResolvedValue({ wishlists: lists });
  }

  afterEach(async () => {
    vi.restoreAllMocks();
    await i18n.changeLanguage("en");
  });

  it("says in plain words what the panel is for, in both languages", async () => {
    await i18n.changeLanguage("en");
    mockLists([fixtureTreasurerWishlist]);
    const { unmount } = render(<TreasurerWishlistsPanel adminKey="test-key" />);
    expect(await screen.findByRole("heading", { name: "Wishlists" })).toBeInTheDocument();
    expect(screen.getByText(/add gear, set how many the crew needs, then publish it/)).toBeInTheDocument();
    expect(screen.getByLabelText("List to edit")).toBe(screen.getByTestId("wishlist-treasurer-select"));
    unmount();

    await i18n.changeLanguage("fr");
    render(<TreasurerWishlistsPanel adminKey="test-key" />);
    expect(await screen.findByRole("heading", { name: "Listes de souhaits" })).toBeInTheDocument();
    expect(screen.getByLabelText("Liste à modifier")).toBeInTheDocument();
  });

  it("shows a draft as hidden from visitors, with Publish as its only state action", async () => {
    await i18n.changeLanguage("en");
    mockLists([{ ...fixtureTreasurerWishlist, published: false }]);
    render(<TreasurerWishlistsPanel adminKey="test-key" />);
    const state = await screen.findByTestId("wishlist-published-state");
    expect(state).toHaveTextContent("Draft · visitors do not see this list yet.");
    expect(screen.getByTestId("wishlist-publish")).toBeInTheDocument();
    expect(screen.queryByTestId("wishlist-unpublish")).toBeNull();
    expect(screen.queryByTestId("wishlist-public-link")).toBeNull();
  });

  it("shows a published list as public, with a link to the public page and Unpublish only", async () => {
    await i18n.changeLanguage("en");
    mockLists([{ ...fixtureTreasurerWishlist, published: true }]);
    render(<TreasurerWishlistsPanel adminKey="test-key" />);
    const state = await screen.findByTestId("wishlist-published-state");
    expect(state).toHaveTextContent("Published · visitors see this list and can fund it.");
    const link = screen.getByTestId("wishlist-public-link");
    expect(link).toHaveAttribute("href", "/escales/wishlists");
    expect(link).toHaveAttribute("target", "_blank");
    expect(screen.getByTestId("wishlist-unpublish")).toBeInTheDocument();
    expect(screen.queryByTestId("wishlist-publish")).toBeNull();
  });

  it("fills the quantity from the catalogue: 6 for a personal item, 1 for a boat item, and sends it", async () => {
    const user = userEvent.setup();
    await i18n.changeLanguage("en");
    mockLists([{ ...fixtureTreasurerWishlist, items: [] }]);
    const add = vi.spyOn(escalesApi, "addTreasurerWishlistItem").mockResolvedValue({ ...fixtureTreasurerWishlist, items: [] });
    render(<TreasurerWishlistsPanel adminKey="test-key" />);
    const pick = await screen.findByTestId("wishlist-catalog-pick");
    const quantity = screen.getByTestId("wishlist-add-quantity");

    await user.selectOptions(pick, "vest-1");
    expect(quantity).toHaveValue(6);
    await user.selectOptions(pick, "radio-1");
    expect(quantity).toHaveValue(1);
    expect(screen.getByText(/6 for personal items \(one per crew member\), 1 for boat items/)).toBeInTheDocument();

    await user.selectOptions(pick, "vest-1");
    await user.click(screen.getByTestId("wishlist-add-submit"));
    await waitFor(() =>
      expect(add).toHaveBeenCalledWith("test-key", fixtureTreasurerWishlist._id, {
        channel3_product_id: "vest-1",
        quantity: 6,
        allow_optional: false,
      }),
    );
  });

  it("counts the items, and says so when a list is empty", async () => {
    await i18n.changeLanguage("en");
    mockLists([{ ...fixtureTreasurerWishlist, items: [] }]);
    render(<TreasurerWishlistsPanel adminKey="test-key" />);
    expect(await screen.findByRole("heading", { name: "0 items on this list" })).toBeInTheDocument();
    expect(screen.getByTestId("wishlist-treasurer-no-items")).toHaveTextContent(
      "Nothing on this list yet. Add gear from the catalogue below.",
    );
  });

  it("names each Remove button after its item", async () => {
    await i18n.changeLanguage("en");
    mockLists([{ ...fixtureTreasurerWishlist, items: [{ channel3_product_id: "vest-1", quantity: 6 }] }]);
    render(<TreasurerWishlistsPanel adminKey="test-key" />);
    expect(await screen.findByRole("button", { name: "Remove Life vest" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "1 item on this list" })).toBeInTheDocument();
  });

  it("invites to create the first list when there is none, and keeps the create form at hand", async () => {
    await i18n.changeLanguage("en");
    mockLists([]);
    render(<TreasurerWishlistsPanel adminKey="test-key" />);
    expect(await screen.findByTestId("wishlist-treasurer-none")).toHaveTextContent(
      "No wishlist yet. Create the first one below.",
    );
    expect(screen.queryByTestId("wishlist-treasurer-select")).toBeNull();
    expect(screen.getByRole("heading", { name: "Create a new list" })).toBeInTheDocument();
    expect(screen.getByLabelText("Short name (letters and dashes)")).toBe(screen.getByTestId("wishlist-create-slug"));
  });
});

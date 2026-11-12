/** Id of a list's section on the public page, so the treasurer can link to that list. */
export function wishlistAnchor(list: { slug?: string | null; id: string }): string {
  const base = (list.slug || "").trim() || list.id;
  return `wishlist-${base.replace(/[^A-Za-z0-9_-]+/g, "-")}`;
}

/** Public page address that opens on one list. */
export function wishlistPublicHref(list: { slug?: string | null; id: string }): string {
  return `/escales/wishlists#${wishlistAnchor(list)}`;
}

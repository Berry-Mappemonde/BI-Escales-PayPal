import type { Channel3CatalogItem, TreasurerWishlistItem } from "../api/types";
import { wishlistLineQuantity } from "./wishlistLine";

export type WishlistLine =
  | { state: "ready"; item: Channel3CatalogItem; quantity: number }
  | { state: "unavailable"; channel3_product_id: string };

/** Join treasurer stored lines with live catalogue rows (no hardcoded product ids). */
export function linesFromTreasurerItems(
  stored: TreasurerWishlistItem[] | undefined,
  catalogByProductId: Map<string, Channel3CatalogItem>,
): WishlistLine[] {
  const rows = Array.isArray(stored) ? stored : [];
  return rows.map((row) => {
    const productId = String(row.channel3_product_id || "").trim();
    const catalog = productId ? catalogByProductId.get(productId) : undefined;
    if (!catalog) {
      return { state: "unavailable", channel3_product_id: productId || "—" };
    }
    const quantity =
      row.quantity != null && Number.isFinite(Number(row.quantity))
        ? Math.max(1, Math.trunc(Number(row.quantity)))
        : wishlistLineQuantity(catalog);
    return {
      state: "ready",
      item: {
        ...catalog,
        quantity: row.quantity != null ? Math.max(1, Math.trunc(Number(row.quantity))) : undefined,
      },
      quantity,
    };
  });
}

export function catalogMapFromItems(items: Channel3CatalogItem[]): Map<string, Channel3CatalogItem> {
  const map = new Map<string, Channel3CatalogItem>();
  for (const item of items) {
    const id = String(item.channel3_product_id || "").trim();
    if (id) map.set(id, item);
  }
  return map;
}

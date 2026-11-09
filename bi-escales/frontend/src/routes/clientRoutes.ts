/**
 * Client paths served by the SPA (Root.tsx). Keep in sync with backend `spa_client_routes.py`.
 */
export const CLIENT_ROUTES = [
  "/",
  "/en",
  "/fr",
  "/escales/wishlists",
  "/en/escales/wishlists",
  "/fr/escales/wishlists",
] as const;

export type ClientRoute = (typeof CLIENT_ROUTES)[number];

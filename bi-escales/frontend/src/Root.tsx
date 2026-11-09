import App from "./App";
import { WishlistsPage } from "./wishlists/WishlistsPage";

function isWishlistsPath(): boolean {
  const path = (typeof window !== "undefined" ? window.location.pathname : "").replace(/\/$/, "") || "/";
  return path === "/escales/wishlists" || path.endsWith("/escales/wishlists");
}

export default function Root() {
  if (isWishlistsPath()) {
    return <WishlistsPage />;
  }
  return <App />;
}

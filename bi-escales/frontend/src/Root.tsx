import App from "./App";
import { WishlistsPage } from "./wishlists/WishlistsPage";
import { ProjectOnboardingPage } from "./projectOnboarding/ProjectOnboardingPage";
import { ProjectOnboardingReturnPage } from "./projectOnboarding/ProjectOnboardingReturnPage";

// Keep client routes in sync with is_known_spa_path in backend/app/main.py.
function normalizedPath(): string {
  return (typeof window !== "undefined" ? window.location.pathname : "").replace(/\/$/, "") || "/";
}

function isWishlistsPath(): boolean {
  const path = normalizedPath();
  return path === "/escales/wishlists" || path.endsWith("/escales/wishlists");
}

function onboardingRoute(): { kind: "page" | "return"; projectId: string } | null {
  const path = normalizedPath();
  const page = path.match(/^\/projects\/([^/]+)\/onboarding$/);
  if (page) {
    return { kind: "page", projectId: decodeURIComponent(page[1]) };
  }
  const ret = path.match(/^\/projects\/([^/]+)\/onboarding\/return$/);
  if (ret) {
    return { kind: "return", projectId: decodeURIComponent(ret[1]) };
  }
  return null;
}

export default function Root() {
  const onboard = onboardingRoute();
  if (onboard?.kind === "page") {
    return <ProjectOnboardingPage projectId={onboard.projectId} />;
  }
  if (onboard?.kind === "return") {
    return <ProjectOnboardingReturnPage projectId={onboard.projectId} />;
  }
  if (isWishlistsPath()) {
    return <WishlistsPage />;
  }
  return <App />;
}

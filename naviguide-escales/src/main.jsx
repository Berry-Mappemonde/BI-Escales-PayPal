import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import L from "leaflet";
import iconUrl from "leaflet/dist/images/marker-icon.png";
import iconRetinaUrl from "leaflet/dist/images/marker-icon-2x.png";
import shadowUrl from "leaflet/dist/images/marker-shadow.png";
import "leaflet/dist/leaflet.css";
import "./index.css";
import App from "./App.jsx";
import { LangProvider } from "./i18n/LangContext.jsx";
import { captureAdminSecretFromUrl } from "./utils/adminSecret.js";
import { RootErrorBoundary, claimPreloadReload, shouldReloadAfterPreloadError } from "./components/RootErrorBoundary.jsx";

delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({ iconRetinaUrl, iconUrl, shadowUrl });

// `?admin=…` once → stored in this browser, removed from the address bar.
captureAdminSecretFromUrl();

createRoot(document.getElementById("root"), {
  onUncaughtError: (error, info) => console.error("NAVIGUIDE uncaught React error:", error, info),
}).render(
  <RootErrorBoundary>
    <StrictMode>
      <LangProvider>
        <DevCrashProbe />
        <App />
      </LangProvider>
    </StrictMode>
  </RootErrorBoundary>,
);

function DevCrashProbe() {
  const enabled = import.meta.env.DEV || import.meta.env.VITE_NAVIGUIDE_CRASHTEST === "1";
  if (enabled && new URLSearchParams(window.location.search).get("crashtest") === "root") {
    throw new Error("NAVIGUIDE root crash test");
  }
  return enabled ? null : <span hidden data-testid="crash-probe-disabled" />;
}

const preloadReloadState = { inProgress: false };
window.addEventListener("vite:preloadError", (event) => {
  event.preventDefault();
  if (preloadReloadState.inProgress) return;
  try {
    if (shouldReloadAfterPreloadError(window.sessionStorage)) {
      claimPreloadReload(preloadReloadState);
      window.location.reload();
    } else {
      window.dispatchEvent(new Event("naviguide:preload-fatal"));
    }
  } catch (error) {
    console.error("NAVIGUIDE preload error recovery failed:", error);
    window.dispatchEvent(new Event("naviguide:preload-fatal"));
  }
});

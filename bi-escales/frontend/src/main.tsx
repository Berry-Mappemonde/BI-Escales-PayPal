import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { BiShellApp } from "./bi-shell";
import { RootErrorBoundary } from "./components/RootErrorBoundary";
import "./i18n";

function Root() {
  const params = new URLSearchParams(window.location.search);
  const useBiShell = params.get("ui") === "bi-shell" || window.location.hash === "#bi-shell";
  return useBiShell ? <BiShellApp /> : <App />;
}

const rootEl = document.getElementById("root");
if (!rootEl) {
  document.body.innerHTML =
    '<main role="alert" style="min-height:100vh;display:grid;place-items:center;font-family:system-ui;background:#0f172a;color:#f8fafc">Missing #root</main>';
} else {
  createRoot(rootEl).render(
    <StrictMode>
      <RootErrorBoundary>
        <Root />
      </RootErrorBoundary>
    </StrictMode>,
  );
}

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import Root from "./Root";
import { RootErrorBoundary } from "./components/RootErrorBoundary";
import "./i18n";

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

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import Root from "./Root";
import { RootErrorBoundary } from "./components/RootErrorBoundary";
import "./i18n";
import { expectPayPalJsFeatures } from "./paypal/paypalJsVersion";

// Every page requests the feature flags as it starts. PayPal buttons wait for that
// answer before loading an SDK, so the page never loads v5 when paypal_js_v6 is on.
expectPayPalJsFeatures();

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

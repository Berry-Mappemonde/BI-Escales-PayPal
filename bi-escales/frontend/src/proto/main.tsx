import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { ProtoApp } from "./ProtoApp";

const rootEl = document.getElementById("root");
if (rootEl) {
  createRoot(rootEl).render(
    <StrictMode>
      <ProtoApp />
    </StrictMode>,
  );
}

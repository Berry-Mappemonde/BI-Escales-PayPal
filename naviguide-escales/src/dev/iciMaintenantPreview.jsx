import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { LangProvider } from "../i18n/LangContext.jsx";
import { IciMaintenant } from "../components/IciMaintenant.jsx";
import { MOMENT_FIXTURE } from "../hooks/useMoment.js";
import "../index.css";

const light = new URLSearchParams(window.location.search).get("light") === "1";
if (light) document.documentElement.classList.add("light-mode");

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <LangProvider>
      <div className={`h-screen p-4 flex ${light ? "bg-slate-100" : "bg-slate-950"}`}>
        <div className="w-[320px] h-full flex flex-col min-h-0">
          <IciMaintenant moment={MOMENT_FIXTURE} />
        </div>
      </div>
    </LangProvider>
  </StrictMode>,
);

// Only served by the local test runner. All HTTP and SDK operations are mocked.
import React from "react";
import { createRoot } from "react-dom/client";
import { PledgeButton } from "../src/components/PledgeButton";
import i18n from "../src/i18n";

const scenario = new URLSearchParams(window.location.search).get("scenario");
const milestone = scenario === "vault" ? "leg-local" : "dep-mayotte";

void i18n.changeLanguage("en").then(() => {
  createRoot(document.querySelector("#checkout")!).render(<PledgeButton
    values={{ amount_eur: "20.00", description: "Offline authorization fixture", kind: scenario === "project" ? "project_pledge" : scenario === "vault" ? "cabin_leg" : "mile", milestone_id: milestone, target_id: scenario === "project" ? "mock-project" : milestone }}
    onAuthorized={pledge => { document.querySelector("#checkout")!.setAttribute("data-authorized", pledge.status); }}
  />);
});

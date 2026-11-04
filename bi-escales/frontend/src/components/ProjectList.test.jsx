import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { I18nextProvider } from "react-i18next";
import { describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import ProjectList from "./ProjectList.jsx";

vi.mock("./PledgeButton", () => ({
  PledgeButton: ({ values }) => (
    <div data-testid="project-pledge-button" data-kind={values.kind} data-target={values.target_id}>
      {values.amount_eur}
    </div>
  ),
}));

const projects = {
  features: [
    {
      type: "Feature",
      geometry: { type: "Point", coordinates: [-1.16, 46.16] },
      properties: { id: "proj-1", title: "Test project", funder: "Funder" },
    },
  ],
};

function Harness() {
  const [selectedProjectId, setSelectedProjectId] = useState(null);
  return (
    <ProjectList
      projects={projects}
      selectedProjectId={selectedProjectId}
      onSelectProject={setSelectedProjectId}
      onFlyTo={() => {}}
    />
  );
}

describe("ProjectList", () => {
  it("ouvre une promesse project_pledge", async () => {
    await i18n.changeLanguage("fr");
    render(
      <I18nextProvider i18n={i18n}>
        <Harness />
      </I18nextProvider>,
    );
    fireEvent.click(screen.getByTestId("project-pledge-open-proj-1"));
    const btn = await screen.findByTestId("project-pledge-button");
    expect(btn).toHaveAttribute("data-kind", "project_pledge");
    expect(btn).toHaveAttribute("data-target", "proj-1");
    expect(btn).toHaveTextContent("1.00");
  });

  it("affiche le minimum pour un montant vide", async () => {
    await i18n.changeLanguage("en");
    function OpenHarness() {
      const [selectedProjectId, setSelectedProjectId] = useState("proj-1");
      return (
        <ProjectList
          projects={projects}
          selectedProjectId={selectedProjectId}
          onSelectProject={setSelectedProjectId}
          onFlyTo={() => {}}
        />
      );
    }
    render(
      <I18nextProvider i18n={i18n}>
        <OpenHarness />
      </I18nextProvider>,
    );
    fireEvent.change(screen.getByTestId("project-pledge-amount"), { target: { value: "" } });
    expect(screen.getByText(/Minimum 1.00 EUR/)).toBeInTheDocument();
  });
});

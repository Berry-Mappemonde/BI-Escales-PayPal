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

const mixedProjects = {
  features: [
    {
      type: "Feature",
      geometry: { type: "Point", coordinates: [1, 1] },
      properties: { id: "visible", title: "Alpha visible", funder: "A" },
    },
    {
      type: "Feature",
      geometry: { type: "Point", coordinates: [2, 2] },
      properties: { id: "map-pick", title: "Zulu map only", funder: "Z" },
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

  it("affiche format invalide pour trop de décimales ou séparateurs mixtes", async () => {
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
    const input = screen.getByTestId("project-pledge-amount");
    fireEvent.change(input, { target: { value: "1,005" } });
    expect(screen.getByText(/Invalid amount/)).toBeInTheDocument();
    expect(screen.queryByText(/Minimum 1.00 EUR/)).toBeNull();
    fireEvent.change(input, { target: { value: "1.234,56" } });
    expect(screen.getByText(/Invalid amount/)).toBeInTheDocument();
  });

  it("épinglé depuis la carte : formulaire visible malgré le filtre recherche", async () => {
    await i18n.changeLanguage("fr");
    render(
      <I18nextProvider i18n={i18n}>
        <ProjectList
          projects={mixedProjects}
          selectedProjectId="map-pick"
          onSelectProject={() => {}}
          onFlyTo={() => {}}
        />
      </I18nextProvider>,
    );
    fireEvent.change(screen.getByTestId("projects-search-input"), { target: { value: "ZZZNOmatch" } });
    expect(screen.getByTestId("project-row-map-pick")).toBeInTheDocument();
    expect(screen.getByTestId("project-pledge")).toHaveAttribute("data-project-id", "map-pick");
    expect(screen.queryByTestId("project-row-visible")).toBeNull();
  });
});

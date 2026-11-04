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

const stops = [{ name: "La Rochelle", lat: 46.15, lon: -1.15, nm: 0, milestoneId: "dep-la-rochelle" }];

function Harness() {
  const [selectedProjectId, setSelectedProjectId] = useState(null);
  return (
    <ProjectList
      projects={projects}
      routeStops={stops}
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
});

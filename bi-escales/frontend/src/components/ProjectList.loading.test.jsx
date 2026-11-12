/** While the projects file is on its way, the list says so: neither "0" nor "No project found". */
import { render, screen } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import ProjectList from "./ProjectList.jsx";

vi.mock("./PledgeButton", () => ({ PledgeButton: () => null }));

const point = (id, title) => ({ type: "Feature", geometry: { type: "Point", coordinates: [1, 2] }, properties: { id, title, funder: "F" } });
const show = (props) =>
  render(
    <I18nextProvider i18n={i18n}>
      <ProjectList projects={{ features: [] }} featureScope="projects" onFlyTo={() => {}} onSelectProject={() => {}} {...props} />
    </I18nextProvider>,
  );

describe("ProjectList while the projects load", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
  });

  it("shows no count and a loading line", () => {
    show({ loading: true });
    expect(screen.getByRole("heading", { name: "Explore projects" })).toBeInTheDocument();
    expect(screen.queryByTestId("project-list-count")).toBeNull();
    expect(screen.getByTestId("project-list-loading")).toHaveTextContent("Loading projects…");
    expect(screen.getByRole("status")).toBe(screen.getByTestId("project-list-loading"));
    expect(screen.queryByText("No project found.")).toBeNull();
  });

  it("shows the count and the rows once loaded", () => {
    show({ loading: false, projects: { features: [point("p-1", "Reef survey"), point("p-2", "Plastics Initiative")] } });
    expect(screen.getByTestId("project-list-count")).toHaveTextContent("2");
    expect(screen.queryByTestId("project-list-loading")).toBeNull();
    expect(screen.getByTestId("project-item-p-1")).toHaveTextContent("Reef survey");
  });

  it("says no project was found only once the answer is in", () => {
    show({ loading: false });
    expect(screen.getByTestId("project-list-count")).toHaveTextContent("0");
    expect(screen.getByText("No project found.")).toBeInTheDocument();
  });

  it("behaves as before for a caller that does not say whether it is loading", () => {
    show({});
    expect(screen.getByTestId("project-list-count")).toHaveTextContent("0");
    expect(screen.queryByTestId("project-list-loading")).toBeNull();
  });

  it("is written in French too", async () => {
    await i18n.changeLanguage("fr");
    show({ loading: true });
    expect(screen.getByTestId("project-list-loading")).toHaveTextContent("Chargement des projets…");
  });
});

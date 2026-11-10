import { fireEvent, render, screen, within } from "@testing-library/react";
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
  it("shows a clear project heading and localized total metadata", async () => {
    await i18n.changeLanguage("en");
    render(
      <I18nextProvider i18n={i18n}>
        <ProjectList
          projects={{ features: Array.from({ length: 4469 }, (_, index) => ({
            ...projects.features[0],
            properties: { ...projects.features[0].properties, id: `project-${index}` },
          })) }}
        />
      </I18nextProvider>,
    );
    const disclosure = screen.getByTestId("project-list");
    expect(disclosure).not.toHaveAttribute("open");
    fireEvent.click(screen.getByRole("heading", { name: "Explore projects" }).closest("summary"));
    expect(disclosure).toHaveAttribute("open");
    expect(screen.getByTestId("project-list-count")).toHaveTextContent("4,469");
    expect(screen.getByTestId("projects-search-input")).toHaveAttribute("placeholder", "Search projects…");
    expect(screen.getByTestId("projects-list-truncated")).toHaveTextContent("Showing 100 of 4,469 projects");
  });

  it("localizes project copy and metadata in French", async () => {
    await i18n.changeLanguage("fr");
    render(
      <I18nextProvider i18n={i18n}>
        <ProjectList
          projects={{ features: Array.from({ length: 4469 }, (_, index) => ({
            ...projects.features[0],
            properties: { ...projects.features[0].properties, id: `project-${index}` },
          })) }}
        />
      </I18nextProvider>,
    );
    expect(screen.getByRole("heading", { name: "Explorer les projets" })).toBeInTheDocument();
    expect(screen.getByTestId("project-list-count").textContent).toMatch(/4[\s\u00a0\u202f]469/);
    expect(screen.getByTestId("projects-search-input")).toHaveAttribute("placeholder", "Rechercher des projets…");
    expect(screen.getByTestId("projects-list-truncated").textContent).toMatch(/Affichage de 100 projets sur 4[\s\u00a0\u202f]469/);
  });

  it("ouvre une promesse project_pledge", async () => {
    await i18n.changeLanguage("fr");
    render(
      <I18nextProvider i18n={i18n}>
        <Harness />
      </I18nextProvider>,
    );
    fireEvent.click(screen.getByTestId("project-list").querySelector("summary"));
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

  it("shows English gear seed titles on the gear tab", async () => {
    await i18n.changeLanguage("en");
    const gearProjects = {
      features: [
        {
          type: "Feature",
          geometry: { type: "Point", coordinates: [55.45, -20.88] },
          properties: {
            id: "gear-dive-computer-expedition",
            title: "Ordinateur de plongée expedition",
            funder: "Channel3",
            project_kind: "gear_project",
          },
        },
        {
          type: "Feature",
          geometry: { type: "Point", coordinates: [57.65, -20.16] },
          properties: {
            id: "gear-dry-bag-expedition",
            title: "Sacs étanches (lot expédition)",
            funder: "Channel3",
            project_kind: "gear_project",
          },
        },
        {
          type: "Feature",
          geometry: { type: "Point", coordinates: [49.29, -18.14] },
          properties: {
            id: "gear-marine-binoculars",
            title: "Jumelles marines",
            funder: "Channel3",
            project_kind: "gear_project",
          },
        },
      ],
    };
    render(
      <I18nextProvider i18n={i18n}>
        <ProjectList projects={gearProjects} featureScope="gear" onFlyTo={() => {}} />
      </I18nextProvider>,
    );
    fireEvent.click(screen.getByTestId("gear-list").querySelector("summary"));
    expect(screen.getByText("Expedition dive computer")).toBeInTheDocument();
    expect(screen.getByText("Dry bags (expedition lot)")).toBeInTheDocument();
    expect(screen.getByText("Marine binoculars")).toBeInTheDocument();
    expect(screen.queryByText("Ordinateur de plongée expedition")).toBeNull();
  });

  it("gear tab: a Channel3 item's picture leads its row; a row without one has no picture", async () => {
    await i18n.changeLanguage("en");
    const gear = (id, extra) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [55.45, -20.88] },
      properties: { id, funder: "Channel3", project_kind: "gear_project", ...extra },
    });
    const gearProjects = {
      features: [
        gear("gear-with-photo", { title: "Dive computer", channel3_image_url: "https://img.example.test/dive.jpg" }),
        gear("gear-no-photo", { title: "Dry bags", channel3_image_url: "" }),
      ],
    };
    render(
      <I18nextProvider i18n={i18n}>
        <ProjectList projects={gearProjects} featureScope="gear" onFlyTo={() => {}} />
      </I18nextProvider>,
    );
    fireEvent.click(screen.getByTestId("gear-list").querySelector("summary"));

    const withPhoto = within(screen.getByTestId("project-row-gear-with-photo"));
    const photo = withPhoto.getByTestId("gear-row-photo");
    expect(photo).toHaveAttribute("src", "https://img.example.test/dive.jpg");
    expect(photo).toHaveAttribute("alt", "Dive computer");
    expect(photo).toHaveAttribute("loading", "lazy");
    expect(photo).toHaveAttribute("width", "32");
    expect(photo).toHaveAttribute("height", "32");
    // The picture is beside the row's button, not inside it, so the button's name is the title once.
    expect(withPhoto.getByTestId("project-item-gear-with-photo")).toHaveAccessibleName(/^Dive computer/);
    expect(within(withPhoto.getByTestId("project-item-gear-with-photo")).queryByRole("img")).toBeNull();

    expect(within(screen.getByTestId("project-row-gear-no-photo")).queryByRole("img")).toBeNull();
  });

  it("projects tab: a project row never has a picture", async () => {
    await i18n.changeLanguage("en");
    const projects = {
      features: [
        {
          type: "Feature",
          geometry: { type: "Point", coordinates: [1, 2] },
          properties: { id: "p-1", title: "Reef survey", funder: "The Ocean Foundation", channel3_image_url: "https://img.example.test/x.jpg" },
        },
      ],
    };
    render(
      <I18nextProvider i18n={i18n}>
        <ProjectList projects={projects} onFlyTo={() => {}} />
      </I18nextProvider>,
    );
    fireEvent.click(screen.getByTestId("project-list").querySelector("summary"));
    expect(within(screen.getByTestId("project-row-p-1")).queryByRole("img")).toBeNull();
  });

  it("gear tab: funded % visible, Page link hidden until fully funded", async () => {
    await i18n.changeLanguage("fr");
    const gearProjects = {
      features: [
        {
          type: "Feature",
          geometry: { type: "Point", coordinates: [55.45, -20.88] },
          properties: {
            id: "gear-partial",
            title: "Partial gear",
            funder: "Channel3",
            project_kind: "gear_project",
            funded_pct: 42,
            fully_funded: false,
            channel3_buy_url: "https://buy.trychannel3.com/partial",
            url: "https://buy.trychannel3.com/partial",
          },
        },
      ],
    };
    render(
      <I18nextProvider i18n={i18n}>
        <ProjectList projects={gearProjects} featureScope="gear" onFlyTo={() => {}} />
      </I18nextProvider>,
    );
    fireEvent.click(screen.getByTestId("gear-list").querySelector("summary"));
    expect(screen.getByTestId("gear-funded-pct")).toHaveTextContent(/42\s*% financés/);
    expect(screen.queryByTestId("gear-page-link")).toBeNull();
    expect(screen.queryByText("https://trychannel3.com")).toBeNull();
  });

  it("gear tab: shows Page link only when fully funded with a product URL", async () => {
    await i18n.changeLanguage("en");
    const gearProjects = {
      features: [
        {
          type: "Feature",
          geometry: { type: "Point", coordinates: [57.65, -20.16] },
          properties: {
            id: "gear-full",
            title: "Funded gear",
            funder: "Channel3",
            project_kind: "gear_project",
            funded_pct: 100,
            fully_funded: true,
            channel3_buy_url: "https://buy.trychannel3.com/full",
            url: "https://buy.trychannel3.com/full",
          },
        },
      ],
    };
    render(
      <I18nextProvider i18n={i18n}>
        <ProjectList projects={gearProjects} featureScope="gear" onFlyTo={() => {}} />
      </I18nextProvider>,
    );
    fireEvent.click(screen.getByTestId("gear-list").querySelector("summary"));
    const link = screen.getByTestId("gear-page-link");
    expect(link).toHaveAttribute("href", "https://buy.trychannel3.com/full");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it.each(["javascript:alert(1)", "http://buy.trychannel3.com/http-only"])(
    "gear tab: no Page link for unsafe URL %s when fully funded",
    async (badUrl) => {
      await i18n.changeLanguage("en");
      const gearProjects = {
        features: [
          {
            type: "Feature",
            geometry: { type: "Point", coordinates: [57.65, -20.16] },
            properties: {
              id: "gear-unsafe",
              title: "Unsafe gear",
              funder: "Channel3",
              project_kind: "gear_project",
              funded_pct: 100,
              fully_funded: true,
              channel3_buy_url: badUrl,
              url: badUrl,
            },
          },
        ],
      };
      render(
        <I18nextProvider i18n={i18n}>
          <ProjectList projects={gearProjects} featureScope="gear" onFlyTo={() => {}} />
        </I18nextProvider>,
      );
      fireEvent.click(screen.getByTestId("gear-list").querySelector("summary"));
      expect(screen.getByText("Unsafe gear")).toBeInTheDocument();
      expect(screen.queryByTestId("gear-page-link")).toBeNull();
    },
  );

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
    expect(screen.getByTestId("project-list")).toHaveAttribute("open");
    expect(screen.getByTestId("project-row-map-pick")).toBeInTheDocument();
    expect(screen.getByTestId("project-pledge")).toHaveAttribute("data-project-id", "map-pick");
    expect(screen.queryByTestId("project-row-visible")).toBeNull();
  });
});

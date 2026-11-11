/**
 * The Bryntum widget takes the shell's theme and follows a switch, shows one row per
 * stop, and uses a months scale: what makes the calendar look like the rest of the app.
 */
import { act, render, waitFor } from "@testing-library/react";
import { forwardRef } from "react";
import { I18nextProvider } from "react-i18next";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../../i18n";

const seen = vi.hoisted(() => ({ props: [] }));
vi.mock("@bryntum/scheduler-react-community", () => ({
  BryntumScheduler: forwardRef(function MockScheduler(props, _ref) {
    seen.props.push(props);
    return <div data-testid="bryntum-widget" />;
  }),
}));
vi.mock("@bryntum/scheduler-community", () => ({ LocaleManager: { applyLocale: vi.fn() } }));
vi.mock("@bryntum/scheduler-community/locales/scheduler.locale.FrFr.js", () => ({}));
vi.mock("@bryntum/scheduler-community/scheduler.css", () => ({}));
vi.mock("@bryntum/scheduler-community/svalbard-light.css", () => ({}));
vi.mock("@bryntum/scheduler-community/svalbard-dark.css?inline", () => ({ default: ":root { --b-test-dark: 1; }" }));

import BryntumTimeline, { applyBryntumTheme, resetBryntumTimelineModulesForTests } from "./BryntumTimeline.jsx";

const DAY = 24 * 60 * 60 * 1000;
const events = ["La Rochelle", "Ajaccio (Corse)", "Fort-de-France (Martinique)"].map((name, index) => ({
  id: `dep-${index}`,
  name,
  startDate: new Date(Date.UTC(2026, 10, 12) + index * 20 * DAY),
  endDate: new Date(Date.UTC(2026, 10, 15) + index * 20 * DAY),
  milestoneId: `dep-${index}`,
}));
const darkStyles = () => document.head.querySelectorAll('style[data-bryntum-theme="dark"]');
const setShell = (theme) => {
  document.documentElement.dataset.theme = theme;
};

function show(props = {}) {
  return render(
    <I18nextProvider i18n={i18n}>
      <BryntumTimeline events={events} fallback={<p data-testid="fallback" />} {...props} />
    </I18nextProvider>,
  );
}

describe("Bryntum timeline: theme and layout", () => {
  beforeEach(async () => {
    seen.props.length = 0;
    resetBryntumTimelineModulesForTests();
    darkStyles().forEach((node) => node.remove());
    setShell("dark");
    await i18n.changeLanguage("en");
  });
  afterEach(() => {
    darkStyles().forEach((node) => node.remove());
    delete document.documentElement.dataset.theme;
  });

  it("adds Bryntum's dark theme on a dark shell, once", async () => {
    show();
    await waitFor(() => expect(darkStyles()).toHaveLength(1));
    expect(darkStyles()[0].textContent).toContain("--b-test-dark");
    // After the stylesheet the widget loaded, so it wins without more specificity.
    expect(document.head.lastElementChild).toBe(darkStyles()[0]);
  });

  it("adds nothing on a light shell", async () => {
    setShell("light");
    show();
    await waitFor(() => expect(seen.props.length).toBeGreaterThan(0));
    await act(async () => {});
    expect(darkStyles()).toHaveLength(0);
  });

  it("follows a theme switch in both directions, without a reload", async () => {
    show();
    await waitFor(() => expect(darkStyles()).toHaveLength(1));
    await act(async () => setShell("light"));
    await waitFor(() => expect(darkStyles()).toHaveLength(0));
    await act(async () => setShell("dark"));
    await waitFor(() => expect(darkStyles()).toHaveLength(1));
  });

  it("does not add the dark theme if the shell turned light while the file was loading", async () => {
    let deliver;
    const pending = applyBryntumTheme("dark", () => new Promise((resolve) => { deliver = resolve; }));
    setShell("light");
    deliver(":root{}");
    await pending;
    expect(darkStyles()).toHaveLength(0);
  });

  it("stays on the light theme if the dark file cannot be loaded", async () => {
    await applyBryntumTheme("dark", async () => "");
    expect(darkStyles()).toHaveLength(0);
  });

  it("never stacks two dark themes", async () => {
    await applyBryntumTheme("dark", async () => ":root{}");
    await applyBryntumTheme("dark", async () => ":root{}");
    expect(darkStyles()).toHaveLength(1);
    await applyBryntumTheme("light");
    expect(darkStyles()).toHaveLength(0);
  });

  it("shows one row per stop, in route order, each with its own bar", async () => {
    show();
    await waitFor(() => expect(seen.props.length).toBeGreaterThan(0));
    const props = seen.props.at(-1);
    expect(props.resources).toEqual(events.map((event) => ({ id: event.id, name: event.name })));
    expect(props.events.map((event) => [event.resourceId, event.name])).toEqual(events.map((event) => [event.id, event.name]));
    expect(props.events[1].startDate).toBe(events[1].startDate);
    expect(props.events[1].endDate).toBe(events[1].endDate);
  });

  it("uses a months scale, solid bars, and stays read-only", async () => {
    show();
    await waitFor(() => expect(seen.props.length).toBeGreaterThan(0));
    const props = seen.props.at(-1);
    expect(props.viewPreset).toBe("monthAndYear");
    expect(props.eventStyle).toBe("filled");
    expect(props.readOnly).toBe(true);
    expect(props.startDate).toBe(events[0].startDate);
    expect(props.endDate).toBe(events.at(-1).endDate);
  });

  it("is as tall as its rows in the rail, up to a limit, with a narrow name column", async () => {
    show();
    await waitFor(() => expect(seen.props.length).toBeGreaterThan(0));
    expect(seen.props.at(-1)).toMatchObject({ rowHeight: 32, height: 64 + 3 * 32 });
    expect(seen.props.at(-1).columns[0]).toMatchObject({ field: "name", width: 132, text: "Stopover calendar" });

    seen.props.length = 0;
    const many = Array.from({ length: 40 }, (_unused, index) => ({ ...events[0], id: `dep-many-${index}` }));
    show({ events: many });
    await waitFor(() => expect(seen.props.length).toBeGreaterThan(0));
    expect(seen.props.at(-1).height).toBe(420);
  });

  it("shows every row and a wider name column where it is given the room", async () => {
    const many = Array.from({ length: 17 }, (_unused, index) => ({ ...events[0], id: `dep-all-${index}` }));
    show({ events: many, nameWidth: 220, maxHeight: Number.POSITIVE_INFINITY });
    await waitFor(() => expect(seen.props.length).toBeGreaterThan(0));
    expect(seen.props.at(-1).height).toBe(64 + 17 * 32);
    expect(seen.props.at(-1).columns[0].width).toBe(220);
  });
});

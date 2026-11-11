import { afterEach, describe, expect, it, vi } from "vitest";
import { applyV6ButtonLook, v6ButtonColorClass, v6CardFieldStyle } from "./paypalLookV6";
import { buildV6Adapter } from "./paypalSdkV6";
import { crewButtonStyle } from "../../components/CrewSubscribeButton";

const session = () => ({ start: vi.fn(), destroy: vi.fn(), hasReturned: () => false, resume: vi.fn() });
const eligibleAll = { isEligible: () => true, getDetails: () => ({ countryCode: "FR", productCode: "PAYLATER" }) };

describe("v6 button look", () => {
  it("maps each v5 colour to the v6 class, and silver to white (v6 has no silver)", () => {
    expect(v6ButtonColorClass("gold")).toBe("paypal-gold");
    expect(v6ButtonColorClass("blue")).toBe("paypal-blue");
    expect(v6ButtonColorClass("white")).toBe("paypal-white");
    expect(v6ButtonColorClass("black")).toBe("paypal-black");
    expect(v6ButtonColorClass("silver")).toBe("paypal-white");
    expect(v6ButtonColorClass(" Black ")).toBe("paypal-black");
  });

  it("uses gold, PayPal's default, when no colour is asked for", () => {
    expect(v6ButtonColorClass(undefined)).toBe("paypal-gold");
    expect(v6ButtonColorClass("")).toBe("paypal-gold");
    expect(v6ButtonColorClass("tangerine")).toBe("paypal-gold");
  });

  it("gives the Crew button its quiet v5 look in both themes: 32 px, full width, black or white", () => {
    const dark = document.createElement("paypal-button");
    applyV6ButtonLook(dark, crewButtonStyle("dark"));
    expect(dark.className).toBe("paypal-black");
    expect(dark.style.height).toBe("32px");
    expect(dark.style.width).toBe("100%");
    expect(dark.style.display).toBe("block");

    const light = document.createElement("paypal-button");
    applyV6ButtonLook(light, crewButtonStyle("light"));
    expect(light.className).toBe("paypal-white");
    expect(light.style.height).toBe("32px");
    expect(light.style.width).toBe("100%");
  });

  it("makes the stop sheet's pay button full width and leaves PayPal's own height", () => {
    const element = document.createElement("paypal-button");
    applyV6ButtonLook(element, { layout: "vertical", label: "pay" });
    expect(element.className).toBe("paypal-gold");
    expect(element.style.width).toBe("100%");
    expect(element.style.height).toBe("");
  });

  it("replaces an earlier colour instead of stacking classes", () => {
    const element = document.createElement("paypal-button");
    element.classList.add("kept");
    applyV6ButtonLook(element, { color: "black" });
    applyV6ButtonLook(element, { color: "silver" });
    expect([...element.classList].sort()).toEqual(["kept", "paypal-white"]);
  });

  it.each([10, 24, 56, 400, Number.NaN])("ignores a height outside PayPal's 25-55 px (%s)", (height) => {
    const element = document.createElement("paypal-button");
    applyV6ButtonLook(element, { height });
    expect(element.style.height).toBe("");
  });
});

describe("v6 adapter applies the look", () => {
  afterEach(() => {
    document.body.innerHTML = "";
    delete document.documentElement.dataset.theme;
  });

  it("renders the subscribe button with the Crew style it was given", async () => {
    const sdk = { createPayPalSubscriptionPaymentSession: () => session() };
    const host = document.body.appendChild(document.createElement("div"));
    const adapter = buildV6Adapter(sdk as never, eligibleAll as never);
    await adapter.Buttons!({ style: crewButtonStyle("dark"), createSubscription: vi.fn(), onApprove: vi.fn() }).render(host);
    const button = host.querySelector("paypal-button") as HTMLElement;
    expect(button.getAttribute("type")).toBe("subscribe");
    expect(button.classList.contains("paypal-black")).toBe(true);
    expect(button.classList.contains("paypal-gold")).toBe(false);
    expect(button.style.height).toBe("32px");
    expect(button.style.width).toBe("100%");
  });

  it("renders the pay button gold and full width, with Pay Later stacked under it at the same width", async () => {
    const sdk = {
      createPayPalOneTimePaymentSession: () => session(),
      createPayLaterOneTimePaymentSession: () => session(),
    };
    const host = document.body.appendChild(document.createElement("div"));
    const adapter = buildV6Adapter(sdk as never, eligibleAll as never, false, "capture");
    await adapter
      .Buttons!({ style: { layout: "vertical", label: "donate" }, offerPayLater: true, createOrder: vi.fn(), onApprove: vi.fn() })
      .render(host);
    const button = host.querySelector("paypal-button") as HTMLElement;
    expect(button.getAttribute("type")).toBe("donate");
    expect(button.classList.contains("paypal-gold")).toBe(true);
    expect(button.style.width).toBe("100%");
    expect(button.style.height).toBe("");
    const later = host.querySelector("paypal-pay-later-button") as HTMLElement;
    expect(later.style.width).toBe("100%");
    expect(later.style.display).toBe("block");
    expect(later.style.marginTop).toBe("8px");
    expect([...host.children].map((node) => node.tagName.toLowerCase())).toEqual(["paypal-button", "paypal-pay-later-button"]);
  });

  it("styles each card field for the shell's theme when the field is created", async () => {
    const created: Array<{ type: string; style?: Record<string, Record<string, string>> }> = [];
    const sdk = {
      createCardFieldsOneTimePaymentSession: () => ({
        createCardFieldsComponent: (options: { type: string; style?: Record<string, Record<string, string>> }) => {
          created.push(options);
          return Object.assign(document.createElement("div"), { destroy: vi.fn() });
        },
        submit: vi.fn(),
        destroy: vi.fn(),
      }),
    };
    const adapter = buildV6Adapter(sdk as never, eligibleAll as never);
    const cards = adapter.CardFields!({ createOrder: vi.fn(), onApprove: vi.fn() }) as Record<string, any>;
    const host = document.body.appendChild(document.createElement("div"));
    await cards.NumberField().render(host);
    document.documentElement.dataset.theme = "light";
    await cards.CVVField().render(host);

    expect(created.map((options) => options.type)).toEqual(["number", "cvv"]);
    // Dark shell: dark field, light text. Not PayPal's default white box.
    expect(created[0].style!.input).toMatchObject({ background: "#1f1f1f", color: "#ededed", border: "1px solid #333333" });
    expect(created[0].style!["input::placeholder"]).toEqual({ color: "#8f8f8f" });
    // Light shell: the light palette.
    expect(created[1].style!.input).toMatchObject({ background: "#f7f7f6", color: "#171717", border: "1px solid #cfcfcc" });
  });
});

describe("v6 card field style", () => {
  afterEach(() => {
    delete document.documentElement.dataset.theme;
    document.documentElement.removeAttribute("style");
  });

  it("uses only selectors and properties v6 card fields accept", () => {
    const selectors = new Set([".invalid", ".invalid.focus", "input", "input.disabled", "input.focus", "input.invalid", "input.valid", "input::placeholder", "label", "label.disabled", "label.focus", "label.invalid", "label.valid", "label::placeholder"]);
    const properties = new Set(["appearance", "background", "border", "borderRadius", "boxShadow", "color", "direction", "font", "fontFamily", "fontSize", "fontSizeAdjust", "fontStretch", "fontStyle", "fontVariant", "fontVariantAlternates", "fontVariantCaps", "fontVariantEastAsian", "fontVariantLigatures", "fontVariantNumeric", "fontWeight", "height", "letterSpacing", "lineHeight", "opacity", "outline", "padding", "paddingBottom", "paddingLeft", "paddingRight", "paddingTop", "textShadow", "transition"]);
    for (const theme of ["dark", "light"]) {
      document.documentElement.dataset.theme = theme;
      for (const [selector, rules] of Object.entries(v6CardFieldStyle())) {
        expect(selectors.has(selector), selector).toBe(true);
        for (const property of Object.keys(rules as object)) expect(properties.has(property), property).toBe(true);
      }
    }
  });

  it("keeps inputs at 16 px so a phone does not zoom the page on focus", () => {
    expect(v6CardFieldStyle().input!.fontSize).toBe("16px");
  });

  it("follows the page's own tokens when they are plain colours, and ignores anything else", () => {
    document.documentElement.style.setProperty("--color-raised", "#101214");
    document.documentElement.style.setProperty("--color-fg", "color-mix(in oklab, white 80%, black)");
    const style = v6CardFieldStyle();
    expect(style.input!.background).toBe("#101214");
    expect(style.input!.color).toBe("#ededed"); // the dark fallback, not a function PayPal's iframe cannot resolve
  });

  it("marks an invalid field in the theme's danger colour", () => {
    expect(v6CardFieldStyle()["input.invalid"]).toEqual({ color: "#eb5a5a", border: "1px solid #eb5a5a" });
    document.documentElement.dataset.theme = "light";
    expect(v6CardFieldStyle()["input.invalid"]).toEqual({ color: "#c9302c", border: "1px solid #c9302c" });
  });
});

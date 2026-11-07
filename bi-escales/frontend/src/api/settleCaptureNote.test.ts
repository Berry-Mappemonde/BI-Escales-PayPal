import { describe, expect, it } from "vitest";
import i18n from "../i18n";
import { formatSettleCaptureNote } from "./settleCaptureNote";

describe("formatSettleCaptureNote", () => {
  it("lists PayPal capture id and status after settle", async () => {
    await i18n.changeLanguage("en");
    const text = formatSettleCaptureNote(i18n.t.bind(i18n), {
      now: "2027-06-01T00:00:00+00:00",
      actions: [
        {
          pledge_id: "abc123",
          action: "capture",
          status: "captured",
          capture_id: "CAP-SANDBOX-1",
          paypal_status: "COMPLETED",
        },
      ],
    });
    expect(text).toContain("PayPal sandbox capture");
    expect(text).toContain("CAP-SANDBOX-1");
    expect(text).toContain("captured");
    expect(text).toContain("abc123");
  });

  it("uses French labels", async () => {
    await i18n.changeLanguage("fr");
    const text = formatSettleCaptureNote(i18n.t.bind(i18n), {
      actions: [{ pledge_id: "x", action: "capture", status: "captured", capture_id: "CAP-FR" }],
    });
    expect(text).toContain("Capture sandbox PayPal");
    expect(text).toContain("CAP-FR");
  });
});

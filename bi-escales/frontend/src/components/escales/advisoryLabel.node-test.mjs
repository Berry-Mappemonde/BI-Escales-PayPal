import assert from "node:assert/strict";
import test from "node:test";

import { advisoryView } from "./advisoryLabel.js";

test("a validated model proposal is labelled Advisory", () => {
  const view = advisoryView({
    advisory: true,
    label: "advisory",
    proposal: "capture",
    reason: "evidence met",
    dropped: false,
  });
  assert.equal(view.label, "Advisory");
  assert.equal(view.proposal, "capture");
  assert.equal(view.dropped, false);
});

test("a dropped 28-day reauthorize stays advisory and is not the action", () => {
  const view = advisoryView({
    advisory: true,
    proposal: null,
    reason: "authorization still valid: younger than 29 days",
    raw_proposal: "reauthorize",
    raw_reason: "the 28-day authorization has expired",
    dropped: true,
  });
  assert.equal(view.label, "Advisory");
  assert.equal(view.proposal, "");
  assert.equal(view.dropped, true);
  assert.equal(view.reason.includes("expired"), false);
});

test("a missing or non-advisory payload is not shown", () => {
  assert.equal(advisoryView(null), null);
  assert.equal(advisoryView({ proposal: "void", reason: "expired" }), null);
  assert.equal(advisoryView({ advisory: true, proposal: null, reason: "", dropped: false }), null);
});

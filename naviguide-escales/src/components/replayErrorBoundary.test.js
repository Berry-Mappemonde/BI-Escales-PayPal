import { describe, it } from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { ReplayErrorBoundary, REPLAY_ERROR_COPY } from "./rootErrorBoundaryCore.js";

describe("replay error boundary", () => {
  it("renders the bilingual retry fallback after a child render error", () => {
    function ThrowingChild() { throw new Error("film render failed"); }
    const boundary = new ReplayErrorBoundary({ children: React.createElement(ThrowingChild) });
    boundary.state = ReplayErrorBoundary.getDerivedStateFromError(new Error("film render failed"));

    const fallback = boundary.render();
    const copy = REPLAY_ERROR_COPY[fallback.props.lang];
    assert.equal(fallback.props["data-testid"], "replay-error-fallback");
    assert.equal(fallback.props.children[0].props.children[0], copy.message);
    assert.equal(fallback.props.children[1].props.children, copy.retry);
    assert.equal(REPLAY_ERROR_COPY.en.message, "Replay hit an error.");
    assert.equal(REPLAY_ERROR_COPY.en.retry, "Retry replay");
  });
});

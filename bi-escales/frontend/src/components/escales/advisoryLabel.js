/**
 * The model proposal is advisory. It never replaces the code decision.
 * Returns null when there is nothing to show.
 */
export function advisoryView(llmProposal) {
  if (!llmProposal || llmProposal.advisory !== true) return null;
  const proposal = llmProposal.proposal || "";
  const reason = llmProposal.reason || "";
  const dropped = Boolean(llmProposal.dropped);
  if (!proposal && !reason && !dropped) return null;
  return {
    label: "Advisory",
    proposal,
    reason,
    dropped,
  };
}

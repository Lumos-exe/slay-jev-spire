# Native action transactions

The old controller inferred command completion from card-specific before/after
effects. That confuses input delivery with game outcomes and fails for effects
that cancel each other (for example Warcry followed by Dark Embrace).

The replacement contract is:

1. Each action has a unique ID, game-process epoch, expected native state revision,
   and exact generated command. Persist it before sending.
2. The native bridge checks the revision, deduplicates IDs, then calls the existing
   CommunicationMod executor. Native acceptance and settlement are separate.
3. Settlement is the next native decision boundary after command execution was
   registered. It is independent of card names and final numerical differences.
4. Only the matching settled receipt commits an action. Effects are audited
   separately; a missing predicted effect is not an input acknowledgement failure.
5. Lost acknowledgements cause receipt queries, then at most a bounded resend of
   the SAME ID. Accepted actions are never resent. Stale revisions are rejected
   before execution. Controller restarts reconcile the durable pending ID.
6. Live Jev runs require the new capability. Legacy effect confirmation remains
   available for old offline fixtures, not as a silent live fallback.

Acceptance includes stale/duplicate/rejected/late receipts, identical before/after
states, transient selection screens, controller recovery, and several actual runs.
Every run must report technical stops separately from combat defeats. Improvements
to combat ranking must be tied to observed failures, not mistaken for receipt fixes.

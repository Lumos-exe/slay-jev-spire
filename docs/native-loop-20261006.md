# Native decision loop, 2026-10-06

## Architectural correction

The former production path coupled legal candidate generation to a partial
handwritten simulator. Unknown cards, relics and powers therefore became ongoing
implementation work. A registry export alone would not fix that dependency.

Production now observes the game, offers current native legal actions to Jev,
executes the returned choice through the native transaction protocol, then observes
the result. The experimental enumerator remains opt-in (`JEV_PLANNING_MODE=enumerate`).
No utility score or probability argmax replaces the model's returned choice.

CardLibrary and RelicLibrary are exported at game initialization. Live fields take
precedence over prototypes. Unregistered observed content can supplement the file;
missing entries do not veto actions. Callback reflection documents actual loaded
overrides, but is neither executable effect semantics nor proof that no other
effects exist. Monster strategy annotations still contain handwritten knowledge;
this change does not establish complete monster-mechanism coverage.

## Verified native export

Windows staging directory: `C:\Users\17469\MyFiles\workspace\slay_native_loop_01`.
Bridge 0.4.2, ZHS. Real cold startup exported 370 cards from 370 registered cards,
178 relics, zero recorded export failures, and no missing upgrade records among
cards marked upgradeable. Local artifact: `data/native-catalog.json`.

The Windows suite passed 377 tests before launch. The installed JAR was replaced
only after the previous GAME_OVER process had exited. The new game reached its
main menu before model probes ran.

## Model probes and limitations

Eight predeclared cases, three orders each, three protocols, identical available
actions per case/order. Evidence: `logs/native-loop/remote-probes-01-fixed/`.
Actual returned model: `jev-1.13.0`.

| Input/protocol | Passed checks | Median latency | Requests per decision |
| --- | ---: | ---: | ---: |
| Native baseline | 16/24 | 937 ms | 1 |
| Readable native actions | 18/24 | 953 ms | 1 |
| Readable + challenger + pair | 18/24 | 2851.5 ms | 3 |

These are tactical checks, not optimal-action recall or whole-run win rates.
The Sentry oracle accepts plays but rejects all potion actions; its two baseline
misses selected a potion and cannot automatically be called tactical errors.
The gremlin checks only test whether the agent avoids immediate END, not whether
its selected play is best. Three immediate-kill controls passed for every profile.

All profiles failed all three Hex waiting checks and all three synthetic Nob
waiting checks. Actual request bodies contain Hex's status-generation description,
the enemy DEBUFF intent, and Nob's skill-triggered Strength description. Thus the
information reached the provider; repeated comparison did not resolve these
decisions. Remaining hypotheses include representation burden and model capability.
No experiment here separates them completely.

Additional synthetic, short-text controls (`logs/native-loop/waiting-semantics-01`)
remove the game transport and template representation. Across three repeats and
two variants (implicit rules / explicit block expiry), Nob waiting, lethal block
and immediate kill each passed 6/6. Hex waiting failed 6/6, including the explicit
block-expiry variant. This is evidence against explaining every failure solely
as missing transport data or solely as context size. These simplified
counterfactuals are not paired reproductions of the full live states.

The production default is therefore the single-pass readable protocol
(`JEV_COMBAT_PROTOCOL=temporal`); three-pass review remains explicit opt-in.

The first probe batch had 72 HTTP 401 failures due to a new metadata-loop variable
shadowing the SDK API-key variable. Fixed locally and in staging; SDK integration
now asserts exact credential forwarding. Those failures are retained separately
under `remote-probes-01` and excluded from policy measurements. No key was logged.

## Remaining acceptance work

Do not declare success from export counts, tactical probes, or one Act 1 win.
Next fresh-game batch uses fixed seeds 1062026101 and 1062026102. Keep source and
native JAR fixed within that batch; retain losses and technical stops. After fixes,
require at least three consecutive fresh, predeclared seeds to complete Act 3
before describing the agent as stable across acts. This is an operational gate,
not a statistical claim of a high population win rate.

Batch started at 2026-10-05T19:15:24Z, source hash
`db346772331fffbe19789140a27912ccc7a33f03fe6ab80a102bf63fb7e78f56`.
Windows interactive task: `JevNativeSeries01`; series evidence is under staging
`logs/series/native-loop-01`. First run ID:
`f2ccf0ef-aa21-4934-82db-703fe571bcbd`. Both games have now finished. The first
died to Guardian on floor 16, turn 10, with 51 enemy HP remaining. The second,
`95ef5b38-e389-45a0-bc83-6c4e42a997b3`, died to Guardian on floor 16, turn 15,
with 21 enemy HP remaining. Boss entry HP was 85/88 and 80/80 respectively.
Neither passed Act 1. Local post-default-change suite: 374 passed, 3 skipped.

Full evidence: `logs/native-loop/series-01/`; `audit.json` records 174 and 272
native commits, no duplicate commits or technical stops, and 149 and 236 HTTP
requests, all status 200. Median HTTP latencies were 938 and 953 ms.

## Iteration 02: evidence-led corrections

1. Native screen option descriptions sometimes contained an entire JSON object
   encoded as a string. The normal shared-card encoder could not visit those
   fields. Parse these objects losslessly, preserve annotation suffixes, and run
   options through the same encoder as state. Unknown fields and every candidate
   remain present. In the actual smith replay, input tokens fell from 27,144 to
   20,283 with the same 19 candidates. Paired replays do not establish better
   decisions from this representation change alone.
2. Remove accumulated instructions favoring early damage and discouraging skipped
   card rewards. Keep screen semantics, native facts and whole-run objectives.
   At identical structured state and candidate order, three repeats of each case
   changed the second-Cleave reward from Cleave twice/Armaments once to Armaments
   three times; Offering reward changed from Sever Soul twice/Spot Weakness once
   to Spot Weakness three times; the early shop changed from leave twice/Sever Soul
   once to Flame Barrier twice/Sever Soul once. These are limited tactical changes,
   not a proven win-rate improvement. Evidence: `remote-neutral-prompt-02`.
3. Preserve the observed source card/potion when an action opens a combat selection.
   In the second run's step 207, the consumed Colorless Potion had disappeared from
   the state, and memory only retained its ID. Its native description explicitly
   said the chosen card costs zero this turn. The old prompt tried to reconstruct
   such rules from a partial list of named cards/potions. Replace that list with
   original native source data, clear it when selection closes, and reconstruct
   it by replaying confirmed observations after controller restart. This does not
   infer new-card effects or alter legality.

Source-information replay (`remote-selection-origin-02`) selected Panache in all
three repeats both with and without the preserved Colorless Potion description.
The information-loss fix is verified, but this probe shows no decision improvement.
Do not claim the missing source alone explains that choice.

Account model discovery returned `jev-latest` and `jev-preview`; both returned
`jev-1.13.0` in the 72-probe matrix and produced the same tactical pass counts.
There is no measured basis to switch aliases.

Iteration 02 is staged in `C:\Users\17469\MyFiles\workspace\slay_native_loop_02`.
Repeat seeds 1062026101 and 1062026102 to test these known failures before fresh
holdout seeds. Repeated diagnostic seeds do not count toward the fresh-seed
stability gate above. Do not change the version during the paired batch.
Final candidate tests: Windows 382 passed; local 379 passed, 3 skipped. The Windows
CLI subprocess test now explicitly uses UTF-8 and its earlier decoding warning is
resolved. Native bridge 0.4.2 compiled successfully. During packaging, missing root
entry scripts and AppleDouble files were found and corrected before any gameplay;
subsequent archives disable copyfile metadata and exclude bytecode caches.

Paired batch uses interactive task `JevNativeSeries02` and stage 02
`logs/series/native-loop-02-paired`. Stage 01 is complete and retained as baseline.
The new batch is verified running: first RunId
`874a80cc-41f0-454b-9846-6ea429efd533`. Local and deployed source hashes agree:
`8fec6dbed529c726abf75d6ccd627f6209822e9997dbb426f67dfb9423397e82`.
The paired batch is complete. Seed 1062026101 passed Guardian (20 HP after the
battle) and died at floor 24 to Gremlin Leader, score 200. Seed 1062026102 died at
floor 12 to Gremlin Nob, score 72. There were no recorded technical stops. Thus
the first seed improved over its floor-16 baseline, while the second regressed;
this is not proof of stable policy improvement. Complete evidence is under
`logs/native-loop/series-02/`.

## Iteration 03: generic native subclass fields

The native bridge still had ID-specific export branches for thieves, Guardian,
Wizard, Combust, and bottled relics. Replace these producer branches with one
reflective exporter for actual subclass scalar fields, scalar arrays, enum names,
and typed card references. Preserve inherited fields, distinguish static class
values from instance data, represent non-finite values explicitly, and list
unreadable/unsupported fields. Do not traverse arbitrary object graphs or execute
effect callbacks. Native current move names and damage-entry catalogues are
exported for all monsters. A damage entry is not a forecast or selected intent.

Extension observations are tied to the native decision revision to prevent visual
timers from repeatedly invalidating an otherwise unchanged decision. This does
not cache normalized live gameplay fields, legality, or action receipts. Pure
export tests cover unknown subclasses, shadowed inherited fields, enum methods
that must not execute, arrays, references, and refresh on revision changes.

Removed the adapter's injected `effect: unknown` labels. The actual native
descriptions remain unchanged. A 48-request paired replay (`remote-effect-label-
probe-03`) still passed 18/24 checks in each arm; the two waiting controls remained
wrong. This removal corrects the input contract, not a proven tactical fix.

Windows: 385 tests passed, 0.4.3 compiled. Local: 382 passed, 3 skipped. Real cold
startup exported 370 cards and 178 relics with zero export failures or unreadable
fields, including upgrade records. 723 complex-object fields across definitions
and upgrade entries are explicitly unexpanded. This is not complete executable
mechanism coverage. Artifact: `data/native-catalog-0.4.3.json`.

A read-only isolated-loader probe sampled the old JVM without replacing classes
or executing choices (`field-probes-03`, 6.3 ms). It captured the second game's
terminal state, so it is field-export evidence, not a live decision-quality test.
`context-optimization` measurement principles were applied; no facts were masked
behind external references and no new lossy summary or value pruning was added.

Stage: `C:\Users\17469\MyFiles\workspace\slay_native_loop_03`.
Task: `JevNativeSeries03`; series: `logs/series/native-loop-03-fresh`.
Predeclared fresh seeds: 1062026301, 1062026302, 1062026303. Source hash agrees
between local and Windows:
`7535c4a821dd27d3be30f77c3021325ed422e94e4956e121af60725e5c212d3c`.
First RunId: `b6d71c23-9223-4c4f-b9d9-987f6208f209`. It was verified at floor 5,
67/80 HP in the shop. It subsequently passed the first boss and reached floor 19,
33/80 HP in a Shelled Parasite battle; no final result yet. All three trials remain
subject to the full multi-act gate.

Early third-version measurement: 99 confirmed native actions and a peak request
of 21,363 input tokens at the sampled checkpoint; later floor-19 requests were
about 25,000 tokens. The invalidation audit (`invalidations-03-run0.json`) found
delayed deck updates and discarded-card cost resets, not changed `native_fields`.
Both old and fresh states sometimes share the same protocol revision, so the
independent normalized-state recheck must remain; revision identity alone does
not establish that every game field is unchanged. No extra compression machinery
was introduced without an observed size benefit.

## Third batch results and shop-navigation recovery

The fresh batch did not establish stability. Seed 1062026301 died at floor 22,
score 186 (275 logical calls, 311 actions). Seed 1062026302 also died at floor 22,
score 192 (329 calls, 359 actions). Neither had a recorded technical stop.
Seed 1062026303, RunId `9c93533f-a382-4b55-89ec-8efa3e3d4183`, stopped at floor 3
with `decision_loop` after repeatedly leaving and reopening the same shop.

The semantic exit was incomplete: native LEAVE closes the purchase screen to
SHOP_ROOM, where the old code asked the model whether to reopen the store. Add
NavigationIntent for the already chosen exit. It issues native PROCEED only when
the same run, room, epoch, revision, resources and available native command match
the observed post-LEAVE boundary. Any mismatch invalidates the continuation.
Preserve it in pending journals and reconstruct it from confirmed actions. Do not
reapply loop detection to this already chosen navigation continuation. Candidate
text now explicitly says that LEAVE finishes shopping and exits the room.

Real fixture: `samples/shop_exit_navigation.json`; regression tests cover resource
and identity changes, unavailable PROCEED, avoiding a second model question,
journal recovery, and the existing room-loop guard. Windows 388 passed; local
385 passed, 3 skipped. Python source hash after recovery:
`6b81dfe232cc44f88168521d5c6ef710d70e79c60f5ffb495c3e27b6580bc4e0`.
The JVM and native bridge were not replaced. Controller restart was confirmed,
RunId stayed unchanged, and native navigation steps 47, 63 and 337 each received
a settled PROCEED receipt with resulting screen MAP. This is a recovered diagnostic
run, not an uninterrupted fixed-version validation success.

The original Windows project's `logs/live` junction now points to stage 03.
Its old junction is preserved as
`logs/live-before-native-loop-03-20261006-054525-059`; no log data was deleted.
Original `main.py status` was verified to read the current trial rather than the
obsolete phase-1 logs.

Latest external blocker: SSH to 192.168.3.14 subsequently timed out twice.
A preceding automatic approval-channel disconnection was a review transport
failure, not an unsafe-action ruling; a normal retry passed review but SSH timed
out. The user has been asked whether the VM is powered on or its IP changed.
Do not infer a terminal game result from this loss of observation. The first two
third-batch runs still need full evidence export. The existing series manifest
retains the third trial's technical stop; its monitoring driver has not yet been
restarted because process inspection could not complete. When connectivity returns,
inspect the actual game and monitor processes, preserve this RunId, and resume
the existing manifest only if the monitor is absent. Do not launch a duplicate game.

Blocked-audit checkpoint: the next goal continuation rechecked both .14 and the
previously authorized .13 with the pinned SSH host key; both still timed out.
The subsequent third consecutive goal turn repeated both checks; both timed out
again. The address/power-state clarification is still pending. The goal is now
blocked on restored connectivity or an updated address. No additional gameplay,
terminal run result, or policy validation is claimed from these checks. The full
multi-act stability objective remains incomplete.

## Reconnection and current-board view experiment

On 2026-10-06 the user supplied the new address 192.168.3.15 and requested
continuation. SSH host-key validation succeeded. The recovered third run had
finished at floor 23 against the three Slavers, score 195, with no pending journal.
No series driver was running. The existing driver consumed the remaining records
and completed its manifest without starting another game. Full three-run evidence
is now local under `logs/native-loop/series-03/`. The recorded shop technical stop
and controller-version change are retained, not rewritten as a clean run.

Paired experiment: keep each actual state and every candidate, but add an expanded
current-board view before the complete reference state. No forecasts or value
scores are added. On the previous eight controls, the original view passed 18/24
checks and the expanded view passed 21/24. Nob waiting changed from 0/3 to 3/3;
Hex waiting remained 0/3. Other controls retained their results. Both medians were
953 ms. These checks retain the previously documented oracle limitations and are
not a whole-run win-rate estimate. Evidence: `remote-current-view-04`.

Additional recent failure snapshots (`remote-current-view-recent-04`) did not
establish general improvement. Snake Plant and Cultist choices stayed the same.
The Slavers low-HP case changed from Feed twice/Defend once to Defend twice/Feed
once, but never selected the available Gambler's Brew. Expanded inputs reached
31,142 tokens. The production candidate therefore falls back to the unchanged
reference state and full candidate set only after a provider-confirmed overflow;
it removes the duplicate view before considering the existing group-comparison
path. The complete state is never replaced by a lossy summary.

The shared `native_view.py` implementation matches all 24 recorded experimental
pairs. Tests cover native-value overrides, field removals, preservation of full
reference facts and target indices, and bounded overflow recovery without losing
candidates. Local full suite: 389 passed, 3 skipped. A required-block-against-Nob
countercontrol passed 3/3 in both views: when the skill is required to survive,
the new view does not indiscriminately reject it. Windows 392 tests passed and
the unchanged 0.4.3 bridge compiled successfully. Evidence:
`remote-current-view-countercontrol-04`.

Fourth-version stage: `C:\Users\17469\MyFiles\workspace\slay_native_loop_04`.
Scheduled desktop task: `JevNativeSeries04`.
Series directory: `logs/series/native-loop-04-fresh`.
Predeclared fresh seeds: 1062026401, 1062026402, 1062026403.
Python source hash: `c3414ec8f835aa9b8a324b3b7cbcadd3de5ad1e1915d06d41f22f604a87d8ca4`.
The series monitor uses 60 minutes per game; this changes only monitoring budget,
not model latency, candidate selection, or native execution. Keep the version
fixed within this batch and retain every failure. Whole-run stability remains
unproven despite the narrower tactical-control improvement.

The fourth batch is confirmed running, first RunId
`9b3ffbc8-860e-47f3-8679-b9f9be93a1a0`. At the latest checkpoint it had reached
floor 7, 80/80 HP after combat. The first 117 recorded decisions included 58
current-board requests, 38 standard noncombat requests, and 21 local workflow
actions, with zero encoding retries. This is an early checkpoint, not a completed
run result. The original project's live-log junction now follows stage 04;
the prior stage-03 junction was preserved rather than deleted.

## Fourth-batch event observation repair

The first run reached floor 21 at 69 HP, then stopped with `decision_loop` in
Match and Keep. Native bytecode and CommunicationMod's adapter establish the
cause: this is a finite five-attempt matching UI, not ordinary dialogue. The old
snapshot exposed choice labels but omitted remaining attempts and the selected
face. A repeated visible list was therefore mistaken for lack of progress.

Add the native `matching_cards` observation contract: actual remaining attempts,
phase/readiness, stable board positions, current selectable indices, selected
visible card ID, and card faces already known to CommunicationMod's revealed-card
memory. Unseen card faces are never evaluated or exported; tests verify that the
face supplier is not even invoked for hidden cards. This is an adapter for a
distinct UI protocol and works with arbitrary card identities; no card-name
whitelist or automatic matching strategy is added. No loop-count limit changed.

New bridge 0.4.4 embeds this view in native screen state. For the ongoing 0.4.3 JVM,
a read-only BaseMod subscriber supplied the same view through an atomic sidecar.
The controller accepts it only when epoch, run, room, native revision and choice
order match. Animation/readiness mismatches wait for a fresh native observation.
The existing loaded JAR was not overwritten or its classes redefined.

Windows full suite: 396 passed. Local full suite: 393 passed, 3 skipped. A small
follow-up exposing the already visible selected card ID passed its four targeted
tests on both platforms. Recovery source hash:
`51bd7985d425d671885728688c8d79bde6597c37691879c1bda3cecb4365f797`.
Before restart, the observer confirmed two attempts left, known slots 0=Decay and
1=Bash, ten hidden faces, and matching native room identity. The same RunId then
consumed attempts 2→1→0 and left to MAP at step 327. Neither remaining attempt
matched a pair; this is a technical recovery, not evidence of good matching play.
It subsequently won floor 22 combat but fell from 69 to 24 HP.

The series monitor was absent after the technical stop and is being resumed from
the original manifest via task `JevNativeSeries04Continue`. The original three
seeds remain; old driver logs are preserved. This batch contains a controller
repair and a native-version transition for later runs, so it cannot qualify as
an uninterrupted fixed-version stability validation.

Independent shop-data experiment (`remote-shop-items-05`) added the actual native
item text beside existing purchase criteria, preserving state/options. It changed
the 311-gold healing shop from leave 3/3 to Double Tap 3/3, another act-two shop
from leave 3/3 to Hand Drill 2/3, and a pre-Guardian shop from leave 3/3 to Sling
3/3. Other two shops stayed leave 3/3. This shows sensitivity to merchandise
encoding, not that spending is better or healing is understood. It remains an
offline experiment; production shopping was not changed merely to make it buy.

Continue by inspecting `tools/live_progress.py` and the series manifest on
192.168.3.15, checking the stage path for the current batch. Do not launch a duplicate game. Export completed runs with
`tools/export_run_evidence.py`, retaining HTTP evidence and technical stops.

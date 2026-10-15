# HISTORY — motion-conductor agent history (moved out of AGENTS.md)

> Split out of `AGENTS.md` 2026-09-20 to keep the always-on agent prefix
> lean (token-economics R2, `~/INFRA/loops-and-goals-mgmt/findings/08`).
> Read on demand when you need the chronological record, known issues, or
> external-repo handoffs; `AGENTS.md` holds only rules, contracts and the
> canonical chains.

---

## Session History

### 2026-10-15 — Studiolot mode: generator-ENGINES fallback
- `_resolve_engine_for_studiolot()` no longer hard-fails when the output tree
  has no `00_APPLICATIONS/ENGINES/`: it falls back to the generator's own
  `ENGINES/` (logged, not silent). This lets `--profile/--input_dir/--output_dir`
  runs target project folders outside the studiolot layout (e.g. the film
  workspace) without touching `USER-FILES/04.INPUT/`.
- Tests: `tests/test_engine_resolution.py` (2 cases); suite 155 green.

### 2026-10-15 — Fenced prompt/duration shapes + duration bounds (Seedance 21:9 · 480p)
- Markdown parser supports the film project's fenced shape next to the legacy one:
  a ```prompt fence (every line up to the closing fence becomes the prompt,
  newlines kept) and a ```duration fence (first non-empty line = raw duration,
  same coercion as `duration:`); fence content is never scanned for media or
  metadata and raises no format warnings. A fence that is never closed consumes
  the rest of the file (with a warning). Legacy first-line prompt + `duration:`
  lines, the leading Shape-1 render embed, and the trailing `studio:` block are
  unchanged.
- Alt aliases: `img` → primary slot (silent), `ref` → the declared
  `reference_images` slot (undeclared → warn + primary). A bullet ending up with
  both a primary URL (`img`) and `reference_images` URLs (`ref`) is rejected at
  parse time — bytedance/seedance-2.5 cannot combine `image` with
  `reference_images`.
- Duration bounds (vehicle side only): `build_inputs()` clamps the effective
  numeric duration (bullet `duration:` → frames/fps → profile default) into the
  profile's top-level `duration_min`/`duration_max`; `-1` and tokens (`auto`)
  pass through verbatim — duration is now passed "verbatim within profile
  bounds". `_markdown_duration()` (cost estimation) applies the same clamp so
  estimates match the run. Note: a legacy profile carrying the old default-duration
  `duration_min`/`duration_max` keys now also bounds durations; the
  `normalize_legacy_profile()` `duration_min` → `parameters.duration` mapping is
  unchanged.
- Active profile renamed `USER-FILES/03.PROFILES/seedance-2.5_16x9_720p_5s.yaml`
  → `..._21x9_480p_5s.yaml` (values were already 21:9 · 480p), gains
  `duration_min: 4` / `duration_max: 30`, and `pricing.cost_per_second` 0.23 →
  0.10 (true 480p price; engine TOML note: $0.10/sec at 480p vs $0.23 at 720p).
  Slots and `generate_audio: false` unchanged.
- Docs: AGENTS.md duration wording → "verbatim within profile bounds".
- Tests: 153 green (was 110) with the new fence/alias/clamp cases;
  `python -m pytest tests/ -v`; ruff + black clean.

### 2026-10-01 — W98: Camera-movement presets + `reference_images` merge (cross-repo)
- Six Owner-scoped camera presets (Dolly in/out/left/right, Handheld, Orbit) ship
  as studiolot's bundled **video** defaults: `media_type = "video"`,
  `reference_media = ""` (words-only); `presets.order` 18 → 24
  (`~/MISC/studiolot` commit `ac87c70`). The image panel is unchanged — the six
  filter out for image generators.
- Studiolot's shipped-default + project-init scaffold tests were amended (never
  blanket-relaxed) to the 24-preset world with per-stem media checks
  (`705a128`); a durable schema lock (`tests/test_preset_reference_media.py`,
  `8dc5045`) pins the W95 round-trip and `compose_profile` `reference_images`
  emit/omit behaviour.
- VG implements `GENERATOR_CONTRACT.md` §2f: `build_inputs` merges the composed
  profile's top-level `reference_images` into each input **after** its own
  references — into the declared `reference_images` slot when declared, else
  `reference_urls` — and raises `ConfigurationError` when a declared slot cannot
  be routed (never a silent drop) (`2592c2e`). VG adds no preset parsing and no
  `--preset` flag; the profile's prompt wrap path is unchanged.
- Cross-repo commit model: the M1–M3 halves commit in studiolot, the M4 code +
  plan/docs in VG (this repo). Gates: VG 91 passed + ruff clean; studiolot 2039
  passed / 24 skipped + ruff clean.
- Closure: `~/PLATFORM/theia-platform/docs/handoffs/W98-mc-camera-presets-closure.md`.
- Stale prose: `CONTRIBUTING.md`'s preset-schema paragraph (the old four-field
  shape) was refreshed to the W95 six-field schema, and was corrected to say the
  presets are studiolot-owned (the Generator repos carry no preset code).

### 2026-09-05 — No Silent Media Failures (Fail-Loud Bullet Pipeline)
- `read_bullets()` now REJECTS a bullet loudly instead of silently changing
  intent: parse errors skip the bullet (no more empty-prompt bullets), and
  any unreachable media URL (primary OR named slot — both validated now)
  rejects the bullet with an error. The old silent paths — stripping dead
  URLs and "treating as text-to-video" — are gone.
- Runs fail when every bullet is rejected: standalone returns exit 1,
  studiolot raises `ValidationError` (previously both soft-exited 0).
- `_execute_pipeline()` now logs progress events into the per-file `.log`:
  error-level events and any event carrying `api_payload` (the exact
  payload dict sent to the endpoint) are written via loguru, so the media
  actually passed is visible in the run log instead of living only in an
  overwritten spinner frame.
- Engine (engine-replicate): error events now carry `api_payload` so failed
  API calls log the exact payload that was rejected.
- Tests: parser rejection cases (unreachable primary/named-slot URLs,
  parse failure, all-rejected), engine payload-on-error test. 77 green
  (2 pre-existing auth failures on system Python 3.14 only).

### 2026-09-05 — Engine TOML Catalog Mirrors Live Schemas (21/21)
- All 21 endpoint TOMLs in engine-replicate were swept against their live
  openapi schemas after the p-video gap (missing `no_op`/`save_audio`/
  `disable_safety_filter`/`last_frame_image`) proved the catalog had
  silently drifted from the server.
- New NON-NEGOTIABLE engine policy (engine-replicate AGENTS.md): every
  server-side input MUST be declared in the endpoint TOML; no invented
  params/slots/options; enums, ranges, and defaults mirror the server.
- New gate: `scripts/check_schema_sync.py` (fetches live schemas, diffs
  the catalog, exit 1 on drift) + offline checker-logic tests. Final run:
  21/21 OK. The 11 VID standby YAMLs regenerated to match.
- MC-side: no vehicle changes; `02.STANDBY/` refreshes from the engine
  shelf on the next run. NOTE: `USER-FILES/03.PROFILES/p-video.yaml` is the
  user's activated copy and was NOT touched — copy the refreshed standby
  YAML over it to pick up `last_frame_image` routing.

### 2026-09-05 — Engine: Scalar Params Coerced Against Live Schema (422 fix)
- Live p-video run hit 422 on `input.duration`/`input.fps` (string vs
  integer): the engine-authored VID YAMLs carry TOML select defaults as
  quoted strings. Fixed in the vendored engine (ENGINES/engine-replicate,
  runtime vendor — push via origin repo):
  - `_build_replicate_input()` coerces every parameter via new
    `_coerce_param_value()` (integer/number/boolean against the model
    openapi schema; tokens like `auto` and unknown-schema runs pass
    verbatim); metadata duration override coerced the same way.
  - `_input_props()` resolves `$ref`/`allOf` fragments (new
    `_resolve_schema_refs()`) — p-video declares fps as
    `{"allOf": [{"$ref": "#/components/schemas/fps"}]}`.
  - Verified live: duration/fps → int 5/24; engine tests 63 green.
- MC-side: no vehicle changes this round.

### 2026-09-05 — Alt-Text Routing: Unknown Alt Defaults to Primary Slot
- `_route_image()` no longer raises on unknown alt text: alt matching the
  primary slot name (`image_url_param`) or any unknown alt now feeds the
  primary slot; only declared named alts (profile `slots:`) route to named
  slots. Unknown alts log a warning ("defaulting to primary slot") instead
  of erroring the bullet — this fixes live bullets whose alt text is a
  filename (e.g. `![movie-still.jpg](url)`), which previously parsed as
  an unknown slot, lost the prompt, and died with "Empty prompt after
  applying prefix/suffix".
- `parse_bullet()`/`read_bullets()` gain `primary_slot: str = "image"`;
  both run modes pass `profile.get("image_url_param") or "image"` (kling →
  `start_image`, p-video → `image`).
- Tests: unknown-alt raise test replaced with default-to-primary + warning
  coverage; new cases for primary-name alt routing, custom primary names,
  primary-vs-declared precedence, `read_bullets(primary_slot=...)` wiring.
  73 green + 2 pre-existing test_auth failures (system Python 3.14 only);
  ruff clean on touched files.

### 2026-09-05 — MC YAML-Free: Engine-Owned VID STANDBY Shelf
- MC is now endpoint-agnostic and profile-YAML-free: the 8 committed video
  YAMLs in `USER-FILES/02.STANDBY/` were removed from the repo (only
  `.gitkeep` remains). The Vehicle carries zero profile content — profiles
  are engine configuration and live in the Engine repo.
- The engine owns the STANDBY shelf: `copy_standby_profiles()` now syncs
  the engine's standby profiles on EVERY load (empty-only Q13 rule removed),
  filtered by the Vehicle's declared media type — MC passes
  `MEDIA_TYPE = "VID"` (new `src/constants.py` constant) so only the
  engine's `profiles/standby/VID/` shelf is seeded. Frame Composer mirrors
  this with `MEDIA_TYPE = "IMG"`.
- engine-replicate: standby profiles reorganized into
  `profiles/standby/IMG/` (30 image YAMLs, moved) and
  `profiles/standby/VID/` (11 new video YAMLs authored from the
  `endpoints/VID-Models/` TOML defaults — kling 2.5 turbo pro / 2.6 / v3,
  seedance 2.0 / lite / pro, wan-2.5-i2v, p-video, veo-3, veo-3.1,
  grok-imagine-video). `list_standby_profiles(media_type)` selects the
  shelf (None → all, legacy); loader falls back to a no-arg call on
  TypeError for engines without the parameter.
- Vendored `ENGINES/engine-replicate` clone updated in place with the new
  layout (runtime vendor; push via origin repo). Verified end-to-end:
  VID → 11, IMG → 30, None → 41; p-video YAML flows through
  `normalize_legacy_profile()` + `build_inputs()` (image_url_param=image,
  slots=[audio], named reference routing). Engine 53 green, MC 69 green
  (2 pre-existing test_auth failures on system Python 3.14 env only).

### 2026-09-05 — Console Output Cleanup + First-Run Guidance Panel
- `CONSOLE_FORMAT` in `src/utils/logging.py` drops `{name}:{function}` —
  console logs are now `HH:mm:ss | LEVEL | message`.
- First-run profile guidance (`_print_profile_guidance()` in
  `main_verbose.py`) prints full absolute USER-FILES paths, rich-styled,
  no panel box.

### 2026-09-05 — First-Run No Longer Auto-Activates Profiles
- Removed `_activate_first_profile_if_none()` (Q2): engine installs now seed
  02.STANDBY/ only — 03.PROFILES/ is never auto-populated. After a fresh
  clone + engine install, all profiles live on the STANDBY shelf and the
  user copies one into 03.PROFILES/ to activate it (existing guidance
  message path). `activate_profile()` stays in profiles.py (unused for now,
  kept for the FC-parity surface).
- Regression test `tests/test_first_run.py` locks the behavior: first run
  with populated STANDBY leaves 03.PROFILES/ empty. 70 green, ruff+black
  clean.

### 2026-09-05 — Live-Run 422 Fix (Image List vs String + Legacy Normalization)
- First live API run attempt hit Replicate 422: `input.image: Invalid type.
  Expected: string, given: array`. Root cause (engine-replicate, vendored
  origin/master): `_build_replicate_input` sent URL LISTS to media params that
  are STRING-typed on every live VID schema (start_image, end_image, image,
  last_frame — all strings; only reference_* are arrays).
- Engine fix: `_input_props()` (authenticated, cached, best-effort openapi
  schema fetch — unauthenticated `models.get` 401s) + `_coerce_media_value()`
  (string params → first URL; array params → list; unknown schema → URL-count
  fallback). Tests updated to live-schema shapes + schema-injection cases;
  52 green, black `--line-length 100` clean.
- MC fix: `normalize_legacy_profile()` now maps legacy `params:` →
  `parameters:`, promotes top-level `fps`, maps `duration_min` →
  `parameters.duration` (int preserved — kling duration schema is an integer
  enum [5,10]; the old float default would 422). `build_inputs()` default
  duration 5.0 → 5. 9 new tests (tests/test_profiles.py); 69 green, ruff+black
  clean.
- Verified without billing: real legacy profile + real bullet → payload
  validates cleanly against the live kwaivgi/kling-v2.5-turbo-pro openapi
  schema (jsonschema Draft7).
- Active + standby Kling legacy profiles still say `image_url: image`
  (deprecated-but-valid string key; canonical is `start_image`) — works
  post-fix; regenerate via AISL compose for the canonical key.

### 2026-09-03 — Part 3: AISL `[general]` Chain + Docs Sweep
- AISL (studiolot repo): the endpoint TOML `[general]` table is now inert
  no longer — the AppWizard captures it onto the instance binding (nested
  `general:` table in pipeline.yaml, canonical key order via
  `pipeline/config_io.py`), `config.parse_pipeline` maps it onto the new
  `Application.general` field, and `compose_profile()` flattens the whole
  table into top-level profile keys (Q21: incl. `slots` — named-slot
  routing works from composed profiles; `duration_type` rides along).
  Legacy bindings compose unchanged (getattr guards) and upgrade on
  edit-and-save (Q22); edit-mode re-captures `[general]` from the endpoint
  TOML. Parameters slide unchanged — `[general]` keys stay excluded.
  R3 tests extend the existing mirror files (binding round-trip, compose
  emission, config trio, PREVIEW/dry-run unaffected); suite gate:
  810 passed / same 11 pre-existing failures / 14 skipped; ruff clean.
  Docs swept: PHILOSOPHY §3 (retires `frames:`), user-manual
  Markdown-input.md, VEHICLE_CONTRACT §4d, ENGINE_CONTRACT §3/§5.
- MC side: docs only — AGENTS.md updated (this entry).

### 2026-09-03 — Part 2: Video Input Layer (Duration + Named Payload Slots)
- `bullet_parser.py`: `duration:` line parsed verbatim (int or token like
  `auto`/`-1`; Q8 `duration:` wins over `frames:`); alt-text capture — empty
  alt → primary, named alt → `references[slot]`, unknown alt errors the
  bullet when the profile declares `slots:` (Q9), no schema → primary fallback;
  `read_bullets(declared_slots=...)` wired from both run modes
- `Bullet` TypedDict gains raw `duration` + `references`; `build_inputs()`
  passes duration verbatim within profile bounds into metadata and `references`
  only to engines that accept the field — loud warning for old-datatype
  engines (Q20)
- `normalize_legacy_profile()`: `image_url` → `image_url_param`; profile
  carries slot schema via `slots:`/`required_slots:` + `duration_param_name`
  (Q17 — no runtime TOML lookup; engine TOML `[general]` slots are Part-3
  metadata)
- Cost estimation (Q18): numeric bullet durations used, tokens fall back to
  profile default (`_bullet_duration` in main_verbose)
- engine-replicate (separate repo, branch `mc-fc-parity`): `InputFile` gains
  additive `references: dict[str, list[str]]` (appended last — positional
  order safe); `_build_replicate_input()` routes empty-alt URLs to the
  primary key (`image_url_param` → `reference_param` → `image_input`), named
  slots to their own keys, empty lists omitted unless `required_slots`,
  per-bullet `metadata["duration"]` overrides under `duration_param_name`
  verbatim; 6 VID TOMLs gained `[general] slots` (seedance-* →
  reference_images/videos/audios; kling-* → end_image)
- Gates: MC 60 tests green + ruff clean; engine-replicate 49 tests green
  (exact Seedance-shaped payload dict asserted); studiolot dry-run exit 0
  with no output dir; cost-estimation smoke $0.75 on token bullet;
  end-to-end contract pairing verified (real engine InputFile construction)
- FC regression: 20 passed / 4 failed — all 4 are FC's own pre-existing
  baseline failures (stale assertions in FC's own tests: auth message text,
  `_GENAI` suffix, parser expectations); FC tree untouched, its tests never
  import the engine
- Vendored `ENGINES/engine-replicate` is STALE — needs `git pull` once the
  engine-replicate `mc-fc-parity` changes are pushed to origin; until then
  standalone runs fall back to the Q20 warning path
- `main_verbose.py` at 307 lines (soft limit exceeded, under the 400 hard
  limit — mirrors FC's `main_simple.py`)

### 2026-09-03 — Part 1: FC Parity (Cold-Start + File-Tree Alignment)
- Ported FC's zero-setup `run.py` venv lifecycle (repair broken venv, prefer 3.12/3.11/3.10/3)
- Re-vendored `engine_loader.py` with `EngineLoadContext` (TYPE_CHECKING annotation bug fixed);
  `copy_standby_profiles()` seeds only an empty STANDBY (Q13 — engine ships image profiles)
- Added `engine_contract.py` (InputFile protocol + `validate_input_file`), `datatypes.py`
  (Bullet), `exceptions.py` (PreflightExit/ConfigurationError), `constants.py`
  (DEFAULT_PLATFORM per Q3)
- Auth to FC parity: `get_api_key()` / `get_api_key_interactive()` rename (Q7),
  `SUPPORTED_PLATFORMS`, wizard saves repo-root `.env`, new `auth/env.py`
- Restructured `src/` to mirror FC: `processing/{bullet_parser,profiles,first_run}.py`,
  `engine_helpers.py`, `utils/{logging,path_resolver}.py`; deleted `input/`, `config/`,
  `execution/`, `parsing/` packages
- Behavior ports: `[]` on empty input dir, URL validation + format warnings (HEAD skipped
  on dry-run, Q15), `_apply_cli_overrides`, `_handle_preflight_checks` (video cost math Q6,
  PreflightExit), `relative_dir` mirroring, per-file `.log` via `_TeeStream`, animated rich
  progress, `{timestamp}_VID` output dirs (Q14), studiolot mkdir after preflight (Q16),
  auto-activate first STANDBY profile (Q2)
- requirements.txt: 4 deps only (Q4); pyproject.toml added (ruff/black/pytest)
- 34 tests ported (parser, engine_loader, auth, path_resolver) — all green, ruff clean
- Full cold-start verified end-to-end: venv rebuild → engine auto-install → profile
  auto-activate → dry-run exit 0; real engine load + InputFile construction verified
- `main_verbose.py` at 298 lines (over 250 soft limit, mirrors FC's `main_simple.py`; OK'd
  by R5's "thin entry" scope)

### 2026-08-05 — AGENTS.md rewrite
- Replaced legacy 1094-line documentation with modern FC-pattern AGENTS.md
- Added Architecture: Engine Interface section documenting Vehicle/Engine relationship
- Added Source File Map and CLI Modes sections
- Documented video-specific processing: InputFile.metadata, fps/duration, bullet frame override

### 2026-08-04 — Session 10: Cleanup Regressions + File Split
- Extracted `bullet_reader.py`, `profile_loader.py`, `pipeline.py` from `main_verbose.py`
- Main entry point reduced from 417 → 143 lines
- Added `PipelineContext` dataclass (1 param instead of 7 keyword-only args)
- Added timeout protection to git clone and pip install subprocess calls
- All files under 200-line soft limit — largest: `pipeline.py` at 183

### 2026-08-04 — Session 9: Refactoring Execution
- 14/15 tasks complete: dead code removal, dependency cleanup, auth rework
- `authenticate()` replaces `sys.exit()` with `AuthenticationError` exception
- `load_engine()` split from 75-line monolith into `_find_engine_dir()` +
  `_import_engine_package()` + `load_engine()` orchestrator
- Pipeline deduplication: `_summarize_results()`, `_create_engine()`,
  `_execute_pipeline()` extracted from both run modes
- `_read_bullets()` split: `_parse_bullet_md()` as pure single-file parser
- Legacy profile normalization extracted: `_normalize_legacy_profile()`
- Log filename changed: `replicate_wrapper` → `motion_conductor`

### 2026-08-04 — Engine Interface Migration (Phase 6)
- Converted from direct `import replicate` to Engine interface
- Vendored `engine_loader.py` from studiolot `pipeline/engine_loader.py`
- Added `--input_dir`, `--output_dir`, `--profile` CLI flags for studiolot mode
- Added `--install-default-engine` flag for standalone first-run UX
- Dead code (api/client.py, processing/processor.py, etc.) purged in Phase 12

---

## Known Issues & Technical Debt

### Remaining (2026-09-05)
- `build_inputs()` dynamically imports `engine_{platform}` — inherently fragile
  at module-load time (same issue as FC); the real engine package must already
  be on `sys.path` (via `load_engine()`)
- Live API generation not yet run (would bill the account); payload verified
  against the live openapi schema via jsonschema instead
- `main_verbose.py` at 307 lines — over the 250 soft limit; mirrors FC's
  `main_simple.py` and holds at the 400 hard limit
- **No-prompt bullets degrade softly**: `read_bullets()` logs a warning on
  `ValueError` from `parse_bullet` but still appends the bullet with an empty
  prompt — the engine then fails with "Empty prompt after applying
  prefix/suffix". Fix when MC src/ is next in scope: on `ValueError`, reject
  the bullet (skip append) so the run fails at parse time instead of at the
  engine. (The former unknown-slot half of this issue is resolved — unknown
  alts now default to the primary slot with a warning.)

### Resolved (2026-09-05)
- Replicate 422 "Invalid type. Expected: string, given: array": engine now
  shapes media params against the model openapi schema (string params get a
  single URL; array params keep lists) — see session history
- Legacy `params:`/`fps`/`duration_min` blocks were dropped by the engine
  contract: `normalize_legacy_profile()` now upgrades them into
  `parameters:`; profile default duration is int 5, not float 5.0
- First run auto-activated the first STANDBY profile into 03.PROFILES/
  (Q2): removed — 03.PROFILES/ is never auto-populated

### Resolved (Part 3)
- Endpoint TOML `[general]` was inert metadata: now captured onto bindings,
  parsed into `Application.general`, and flattened into composed profiles
  (AISL side — see session history)

### Resolved (Part 2)
- Video bullets now carry `duration:` (verbatim within profile bounds) + named
  alt slots; payload slot routing + duration override live in engine-replicate
- Cost estimation breaks on token durations: fixed via profile-default
  fallback (Q18)
- Old engines silently dropped named slots: now a loud warning (Q20)

### Resolved (Part 1)
- Test coverage: 34 tests added (parser, engine_loader, auth, path_resolver)
- `src/parsing/` empty directory deleted
- Flat `USER-FILES/05.OUTPUT/`: now timestamped `<YYMMDD_HHMMSS>_VID` run dirs
- `run.py` venv-missing error: now zero-setup bootstrap
- `replicate==1.0.4` pin removed; `rich` added for animated progress

### Resolved (Session 10)
- `main_verbose.py` god-file: 417 → 143 lines (split into 3 new modules)
- Pipeline parameter explosion: 7 keyword-only params → `PipelineContext` dataclass
- Auto-install timeout risk: added `timeout=300` to git clone and pip install

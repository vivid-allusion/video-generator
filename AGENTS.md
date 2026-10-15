## Agent Behaviour Rules

### General Behavior

- MUST: Ask for clarification when requirements are ambiguous
- MUST: Verify all changes work before confirming completion
- SHOULD: Run tests before committing code
- SHOULD: Provide clear explanations for complex changes
- SHOULD NOT: Make assumptions about file locations or project structure

### Error Handling

- MUST: Report errors with full context to the user
- MUST: Continue processing other items when individual items fail
- MUST: Write a verbose error log on ANY generation failure, regardless of
  logging flags — the engine writes a per-item `<base>-<idx>_ERROR.log`
  beside the would-be output (named on the result as `metadata["error_log"]`);
  the vehicle writes one run-level `<output_dir>/<YYMMDD_HHMMSS>_ERROR.log`
  per failed run (run mode, profile path, input root, counts, per-item
  failures, traceback) — parse/preflight rejections never write one
- SHOULD: Suggest solutions when errors occur
- SHOULD: Validate inputs before processing
- SHOULD NOT: Silently ignore errors or warnings

## USER-FILES Protection Rules

### ABSOLUTE FORBIDDEN - USER-FILES/04.INPUT/
- MUST NEVER: Create, delete, modify, move, or rename ANY files in USER-FILES/04.INPUT/
- CAN ONLY: Read files from USER-FILES/04.INPUT/

### General USER-FILES Rules
- MUST: Never create, delete, modify, move, or rename files in USER-FILES/ without explicit permission
- MUST: Ask before any operation in USER-FILES/
- SHOULD: Only read from USER-FILES/04.INPUT/ and write to USER-FILES/05.OUTPUT/
- SHOULD NOT: Implement any auto-cleanup or archiving features

## Project Structure Rules

- MUST: Read inputs only from USER-FILES/04.INPUT/
- MUST: Write outputs only to USER-FILES/05.OUTPUT/ with timestamps (YYMMDD_HHMMSS format)
- SHOULD: Preserve input directory structure in outputs

## Python Code Standards

- MUST: Use type hints for all function signatures
- MUST: Use pathlib.Path for file operations (not os.path)
- SHOULD: Keep functions under 50 lines
- SHOULD: Format with black and lint with ruff
- SHOULD: Add docstrings for all public functions

## Testing Standards

- MUST: Write tests for critical functionality
- SHOULD: Test happy paths and edge cases
- SHOULD: Mock external dependencies
- SHOULD: Keep tests fast and focused

## Configuration Management

- MUST: Use environment variables for sensitive data
- MUST: Validate configuration at startup
- SHOULD: Provide sensible defaults

## Dependency Management

- MUST: Pin exact versions in requirements.txt
- MUST: Use virtual environments
- SHOULD: Keep dependencies minimal

---

## Architecture: Engine Interface

### Core Concept
The Video Generator (Generator) delegates all API/provider logic to Engine plugins.
"The Generator orchestrates. The Engine executes. The profile configures."

VG is a **video generation Generator** — it reads video Markdown files (with
prompts + image URLs + optional frame counts), loads an Engine, and calls
`engine.run()` with `InputFile` objects carrying `metadata = {duration, fps}` per
GENERATOR_CONTRACT.md §4d.

### Engine Loading
- `src/engine_loader.py` — canonical `load_engine()` implementation, vendored
  from studiolot. Mirrors IG's loader exactly.
- Searches `search_paths` for `engine-<platform>/` directories
- Local clones take precedence over pip-installed packages (GENERATOR_CONTRACT §2b)
- Corrupted local engine falls back to pip-installed package

### Supported Platforms
`replicate`, `fal`, `openrouter`, `google`, `beeble`, `evolink` — new engines added by installing the
corresponding package.

### Processing Flow

Standalone mode (TTY):
```
main() → _run_standalone()
  → handle_first_run()            # engine check → TTY wizard → auto-install
                                  #   → STANDBY seed (empty shelf only) —
                                  #   03.PROFILES/ is NEVER auto-populated
  → load_profile_standalone()     # 03.PROFILES/ only — never falls back;
                                  #   empty → guidance to copy from 02.STANDBY/
  → resolve_input_path()          # profile paths block or USER-FILES/04.INPUT/
  → read_markdown()               # parse .md inputs (prompt + URLs + frames +
                                  #   duration + named slots, profile `slots:`)
  → _handle_preflight_checks()    # --cost-estimation / --dry-run → PreflightExit
  → create_timestamped_output_path()  # 05.OUTPUT/<YYMMDD_HHMMSS>_VID/
  → get_api_key()                 # 4-tier (env → pass → .env → wizard fallback)
  → load_engine()
  → _execute_pipeline()           # build inputs → run → report → per-file .log
```

Studiolot mode:
```
main() → _run_studiolot()
  → load_profile_studiolot()      # from --profile path
  → read_markdown()               # HEAD URL validation skipped under --dry-run
  → _handle_preflight_checks()    # before any output_dir.mkdir (Q16)
  → output_dir.mkdir()            # only after preflight passes
  → get_api_key()
  → find_project_engines_dir()    # walk up from --output_dir; none → generator's own ENGINES/
  → load_engine()
  → _execute_pipeline()
```

`_execute_pipeline()` (shared): `build_inputs()` (metadata = `{duration, fps,
relative_dir}`) → rich `Progress` spinner wrapping `engine._on_progress`
(in-place task description, restored in finally) → `engine.run(inputs)` →
`_report_results()` → `write_run_logs()` writes `<file>.log` beside every
generated video (fallback `video_generator_<ts>.log` when nothing generated).
A run that ends with ≥1 failed item — or raises out of `engine.run()` — always
writes a run-level `<output_dir>/<YYMMDD_HHMMSS>_ERROR.log` via
`write_error_log()`, independent of `--logs`.

### Video-Specific Input
- Prompt: a plain first line, or a ```prompt fence (every line to the closing
  ``` becomes the prompt, newlines kept; fence content is never scanned for
  media or metadata)
- Duration/frames: `frames: N` (deprecated back-compat, converted via fps)
  and/or `duration: <value>` — a plain line or a ```duration fence — the value
  verbatim within profile bounds (int or any token like `auto` / `-1`; numeric
  values clamp into the profile's `duration_min`/`duration_max` at build time,
  tokens pass through); `duration:` wins over `frames:` (Q8)
- Named payload slots: `![slot](url)` routes the URL — empty alt, the primary
  slot name (`image_url_param`, e.g. `image`), or an unknown alt all feed the
  primary slot (unknown alt warns and defaults, no longer errors); `img` is a
  silent primary alias, `ref` aliases the declared reference-image slot —
  `reference_images` (Seedance 2.5) or `reference_image_urls` (MiniMax H3),
  first declared wins (undeclared → warn + primary); a declared named alt
  (profile `slots:`) feeds that slot; no schema → primary fallback; a bullet
  mixing a primary image with reference-image URLs is rejected at parse time
  (the model cannot combine them)
- `read_markdown(primary_slot=...)` takes the profile's `image_url_param`
  (default `"image"`); both run modes pass it through
- `build_inputs()` reads `fps` and `duration` from profile `parameters` block,
  and the top-level `duration_min`/`duration_max` bounds
- Each `InputFile.metadata` = `{"duration": int|str|float, "fps": int, "relative_dir": str}`
  — Markdown-file duration passed verbatim within profile bounds (numeric
  values clamp to `duration_min`/`duration_max`; `-1`/tokens pass through)
- `InputFile.references` (additive engine field) carries the named-slot map;
  engines still on the old datatype get a loud warning and drop named refs (Q20)
- `relative_dir` mirrors the Markdown file's folder structure under the output dir
- Cost estimation: numeric Markdown-file durations used, token durations (`auto`,
  `-1`) fall back to the profile default (Q18); the same `duration_min`/
  `duration_max` clamp applies so estimates match the run
- Legacy profiles with `duration_config`/`image_url` blocks are normalized by
  `normalize_legacy_profile()` (`image_url` → `image_url_param`)

### CLI Modes
1. **Standalone mode** (no `--profile`/`--input_dir`/`--output_dir`): reads profile
   from `USER-FILES/03.PROFILES/` (fallback `02.STANDBY/`), inputs from
   `USER-FILES/04.INPUT/`, outputs to `USER-FILES/05.OUTPUT/`
2. **Studiolot mode** (with `--profile --input_dir --output_dir`): explicit paths
   for all three, discovers Engine via `00_APPLICATIONS/ENGINES/` walking up from
   output_dir

---

## Source File Map (current)

| File | Purpose |
|------|---------|
| `run.py` | Zero-setup bootstrap: finds/repairs venv (`venv`, `venv_new`), prefers Python 3.12/3.11/3.10/3, upgrades pip + installs requirements, launches `src.main_verbose` from repo root |
| `src/main_verbose.py` | Thin entry point, CLI routing, both run modes, `_execute_pipeline()` + preflight + CLI overrides |
| `src/cli.py` | Declarative `_ARGUMENTS` list — `--input_dir`, `--output_dir`, `--profile`, `--platform`, `--dry-run`, `--debug`, `--verbose`, `--cost-estimation`, `--no-save-payloads`, `--install-default-engine` (no `--force-png`) |
| `src/constants.py` | `__version__`, `TIMESTAMP_FORMAT`, `DEFAULT_PLATFORM` (canonical home, Q3), `MEDIA_TYPE = "VID"` (declares which engine standby shelf to seed) |
| `src/datatypes.py` | `Markdown` TypedDict — path, prompt, reference_urls, frames, duration (raw), references (named slots) |
| `src/exceptions.py` | `AuthenticationError`, `ConfigurationError`, `ValidationError`, `PreflightExit` |
| `src/engine_contract.py` | `EngineInputFile` protocol + `validate_input_file()` — fail fast on contract mismatch |
| `src/engine_loader.py` | Vendored canonical `load_engine()` with `EngineLoadContext`; `copy_standby_profiles(media_type=...)` syncs the engine-owned VID shelf into `02.STANDBY/` on every load |
| `src/engine_helpers.py` | Discovery (`find_project/generator_engines_dir`), `auto_install_engine` (timeout=300), `build_inputs()` (verbatim-within-profile-bounds duration + references + relative_dir + Q20 old-engine warning), `clamp_duration()`, `load_engine_or_install`, `print_engine_not_found` |
| `src/auth/__init__.py` | 4-tier `get_api_key()` (env → pass → .env → AuthenticationError), `SUPPORTED_PLATFORMS`, interactive wizard (`_prompt_platform`, `_offer_engine_install`, `_prompt_and_save_key` → repo-root `.env`) |
| `src/auth/env.py` | `.env` loading (`get_api_token_from_env`) |
| `src/processing/markdown_parser.py` | `read_markdown()`, `parse_markdown()`, `validate_image_urls()` — prompt (plain line or ```prompt fence) + URLs (`img`/`ref` alt aliases) + `frames:` + `duration:` (or ```duration fence; parsed raw, clamped at build time) + alt-text named slots + `declared_slots` validation, primary/`reference_images` mix rejection, `[]` on empty dir, markdown format warnings, HEAD validation skipped on dry-run (Q15) |
| `src/processing/profiles.py` | `load_profile_standalone()` (no STANDBY fallback), `load_profile_studiolot()`, `normalize_legacy_profile()` (`image_url` → `image_url_param`), `activate_profile()` |
| `src/processing/first_run.py` | `handle_first_run()` — engine check, TTY wizard, auto-install, STANDBY seed; never touches 03.PROFILES/ (Q2 removed), non-TTY guidance |
| `src/utils/logging.py` | loguru + `_TeeStream` capture (encoding is a property) + `write_run_logs()` + `write_error_log()` (run-level `<YYMMDD_HHMMSS>_ERROR.log` on failed runs) |
| `src/utils/path_resolver.py` | Timestamped output dirs `<YYMMDD_HHMMSS>_VID` (Q14) |

## Configuration

- Profiles: YAML files in `USER-FILES/03.PROFILES/` (production) or
  `USER-FILES/02.STANDBY/` (engine-seeded backup; content gitignored, only
  `.gitkeep` tracked)
- Profile format: `platform`, `endpoint`, `parameters` (with `fps`, `duration`),
  `prompt_prefix`, `prompt_suffix`, `pricing`, `paths`
- Video slot keys (Part 2): top-level `image_url_param` (primary input key;
  normalized from legacy `image_url`), `slots:` (declared named slots — enables
  alt-text routing + unknown-alt errors), optional `required_slots:` (emit
  declared-but-unused slots as `[]`), `duration_param_name` (defaults to
  `duration`). No runtime TOML lookup — profiles carry these keys (Q17); the
  engine's endpoint TOML `[general]` slot declarations are Part-3 metadata
- API keys: `REPLICATE_API_TOKEN` env var (primary), also `FAL_KEY`,
  `OPENROUTER_API_KEY`, `GOOGLE_API_KEY`, `BEEBLE_API_KEY`, `EVOLINK_API_KEY` for multi-platform
- .env file: loaded from project root on startup (standalone mode)
- Interactive wizard saves keys to repo-root `.env`; called from
  `handle_first_run()` and as a fallback in `_run_standalone()`
- requirements.txt: only python-dotenv, loguru, PyYAML, rich — Engines vendor
  their own SDK deps (no replicate pin)
- `ENGINES/` is gitignored (vendored at runtime, separate repos)
- Legacy profiles with `Model`/`duration_config`/`image_url`/`params` blocks
  are auto-normalized by `normalize_legacy_profile()` (params→parameters,
  top-level fps promoted, duration_min → parameters.duration)

---

## Twin files — agreed vs accepted divergence (W5 M5, 2026-09-30)

W5 phase_5 settled the studiolot/IG/VG twin set. Each row names the file, the
verdict, and — for a divergence — the one-line reason. **accepted divergence**
is deliberate: do not "fix" such a file back to the other Generator's copy. The
canonical Engine loader is `~/MISC/studiolot/hc/engines.py`.

| File | Verdict | Reason |
|---|---|---|
| `src/engine_loader.py` | **re-vendored (agreed)** | the *loader half* of `hc/engines.py`; byte-identical in IG and VG and to the canonical loader body (three-way diff clean), docstring naming the canonical path. |
| `tests/conftest.py` | **agreed** | already byte-identical (6/6) across the twins — re-vendor was a no-op. |
| `src/auth/env.py` | **agreed** | the only difference was one blank line; IG's form is now shared. |
| `src/utils/logging.py` | **accepted divergence** | VG's `log_file_only` + `write_run_logs(generated_paths, output_dir)` vs IG's header/summary writer — different public APIs. |
| `src/processing/markdown_parser.py` | **accepted divergence** | VG's 289-line parser (7 defs) carries video duration/fps parsing; IG's is 227 lines with 10 defs. |
| `src/engine_helpers.py` | **accepted divergence** | VG's 218-line helpers (10 defs) add `find_generator_engines_dir` and `auto_install_engine(generator_root=…)`; IG's are 173 lines with 9 defs. |
| `src/cli.py` | **accepted divergence** | each generator's own front-end flags (VG's dict table; IG's declarative `_ArgumentSpec`). |
| `run.py` | **accepted divergence** | each Generator's own bootstrap and launch target. |
| `src/processing/profiles.py` | **accepted divergence** | VG's 86-line video profile with `normalize_legacy_profile` vs IG's 36-line still-image profile. |
| `src/utils/path_resolver.py` | **accepted divergence** | VG returns `(Path, project_name)` and uses the `_VID` output suffix; IG returns a `Path`. |
| `src/constants.py` | **accepted divergence** | per-Generator identity: `__version__` 1.0.0 vs 2.1.0 and `MEDIA_TYPE` VID vs IMG. |
| `src/exceptions.py` | **accepted divergence** | VG adds `ValidationError`. |
| `src/datatypes.py` | **accepted divergence** | the Markdown payload shape: VG adds `frames`/`duration`/`references`. |
| `src/engine_contract.py` | **accepted divergence** | the per-Generator mirror of the contract's interface notes. |
| `src/processing/first_run.py` | **accepted divergence** | same length, different first-run flows and helper imports (diffed, not assumed). |
| `src/main_verbose.py` | **slated — kept** by Owner ruling Q3 (2026-09-30) | VG's live entry point (`pyproject.toml` console script, `run.py` target, a test import) — not dead code; no removal, no rename. |

---

## W98 camera presets — loop session notes

- 2026-10-01 · W98 (cross-repo; M1–M3 studiolot, M4–M6 VG) — COMPLETE:
  M1 `ac87c70` six video presets + `presets.order` 18→24, words-only;
  M2 `705a128` default/scaffold suites → 24, per-media scoped not relaxed;
  M3 `8dc5045` durable schema lock (`test_preset_reference_media.py`);
  M4 `2592c2e` VG `build_inputs` merges profile `reference_images` (declared
  slot else `reference_urls`; `ConfigurationError` when unroutable);
  M5 gates both repos green (VG 91, studiolot 2039/24, ruff clean);
  M6 `a18309d` records the outcome in `docs/HISTORY.md` + refreshes CONTRIBUTING.

## History

The chronological record (session history, known issues & technical debt,
external-repo handoffs) moved to [`docs/HISTORY.md`](docs/HISTORY.md) — it is
not loaded every turn. Read it on demand.

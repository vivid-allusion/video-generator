# Architecture — where the Video Generator sits

Helmer is a desktop app for making films with AI. The Video Generator is one of
the Generators Helmer uses; the Helmer Transceiver runs it. This page says how
the pieces fit, so you know where a change belongs.

## The pieces

- **Helmer** — the desktop app. It manages projects, presets and the queue,
  decides *what* to run, and composes the profile for each run. It bundles the
  Transceiver.
- **Helmer Transceiver (`~/MISC/helmer-transceiver`)** — runs the Generators for
  Helmer with `--profile --input_dir --output_dir` (the mode the code calls
  `_run_project()`). Its `hhc/engines.py` is the canonical Engine loader;
  `src/engine_loader.py` is the vendored loader half. It links the Generator's
  `ENGINES/` to the project's `.00_TOOLS/GENERATORS/ENGINES`.
- **Video Generator (this repo)** — parses Markdown job files, loads an Engine,
  runs the generation, writes videos and logs.
- **Engines (`engine-*`)** — one provider's SDK each, plus endpoint TOML files
  describing each model's parameters and settings.

> **The Generator orchestrates, the Engine executes, the profile configures.**
> The Generator never imports a provider SDK; it calls the Engine.

## One run

```
main_verbose → read profile → read Markdown files → preflight (--dry-run /
--cost-estimation) → API key → load Engine → engine.run(inputs) → videos + logs
```

`src/main_verbose.py` routes; `src/processing/` parses and validates;
`src/engine_helpers.py` builds the `InputFile`s (metadata `duration`, `fps`,
`relative_dir`) and finds Engines; `src/auth/` resolves the API key.

## The Markdown job file

Parsed by `src/processing/markdown_parser.py` and
`src/processing/setting_blocks.py`:

````
---
optional front matter on line 1
---
```prompt
the prompt
```

![](url-to-a-first-frame-image)
![ref](url-to-a-reference-image)

duration: 5

```aspect_ratio
16:9
```
````

- Front matter on line 1 is skipped whole.
- The prompt is the first plain line, or a ```` ```prompt ```` fence.
- `![alt](url)` images route by alt text: primary slot, reference images, or a
  slot the profile declares; anything else rejects the file.
- `duration:` (or a ```` ```duration ```` fence) is clamped into the profile's
  bounds; tokens like `auto` pass through.
- Setting blocks (```` ```aspect_ratio ````, ```` ```resolution ````,
  ```` ```audio ````) are accepted only when the model's endpoint file in the
  Engine declares that setting; otherwise the file is rejected before any call.

## Profiles

A profile is the configuration for one run: platform, endpoint, parameters,
prompt prefix/suffix, slots, duration bounds, paths. Helmer composes it per
run; standalone, the Generator reads one from `USER-FILES/03.PROFILES/`. A
composed profile's `reference_images` are appended after each file's own
references.

## Where your change belongs

| Change | Where |
|---|---|
| App behaviour, projects, queue | Helmer |
| Running Generators, the Engine loader | `helmer-transceiver` |
| A new model or provider parameter | the `engine-*` repo (endpoint TOML) |
| Provider SDK logic, auth, request shaping | the `engine-*` repo |
| Video job parsing, profiles, run output | this repo |

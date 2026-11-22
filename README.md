# Video Generator

Generates video from Markdown job files: a prompt, optional image links and
settings, run against a provider's model through an Engine. It is one of the
Generators Helmer (a desktop app for making films with AI) runs through the
Helmer Transceiver, and it also runs on its own from a terminal.

Platforms (`SUPPORTED_PLATFORMS` in `src/auth/__init__.py`): `replicate`, `fal`,
`openrouter`, `google`, `beeble`, `evolink`, `spicyapi`, `openai`, `bytedance`,
`higgsfield`, `oxen`. Each platform is an Engine (`engine-<platform>`) that the
Generator loads; the API key comes from the platform's environment variable
(e.g. `REPLICATE_API_TOKEN`, `FAL_KEY`), `pass`, or the repo-root `.env`.

## Setup

Python 3.10+. `run.py` finds or creates the virtual environment, installs
`requirements.txt` (python-dotenv, loguru, PyYAML, rich) and starts
`src.main_verbose`:

```bash
python run.py
```

Or by hand:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -m src.main_verbose
```

Engines vendor their own SDKs. Where they are found: next to the Generator in
`ENGINES/` (`engine-<platform>/`), or pip-installed. In a Helmer project the
Transceiver links that `ENGINES/` to `<project>/.00_TOOLS/GENERATORS/ENGINES`.
On first run the Generator offers to install the Engine you need.

## The Markdown job file

Put `.md` files in `USER-FILES/04.INPUT/`. One file is one video.

````
---
optional front matter on line 1 — skipped whole
---
```prompt
A cinematic tracking shot through a forest.
Mist, low sun.
```

![](https://example.com/first-frame.jpg)
![ref](https://example.com/reference.jpg)

duration: 5

```aspect_ratio
16:9
```

```resolution
720p
```

```audio
on
```
````

- **Front matter** — a `---` block starting on line 1 is skipped whole.
- **Prompt** — a plain first line, or a ```` ```prompt ```` fence (every line up
  to the closing fence, newlines kept).
- **Images** — `![alt](url)` links. An empty alt, `img`, or the profile's primary
  slot name feeds the primary input (first frame); `ref`, `reference_images` and
  `reference_image_urls` feed the model's reference-image slot; any other alt
  must be a slot the profile declares under `slots:`, else the file is rejected.
  A primary image cannot be mixed with reference images.
- **Duration** — `duration: <value>` on a plain line, or a ```` ```duration ````
  fence. Numbers clamp into the profile's `duration_min`/`duration_max`; tokens
  such as `auto` pass through. (`frames: N` still works, converted via fps.)
- **Setting blocks** — ```` ```aspect_ratio ````, ```` ```resolution ````,
  ```` ```audio ```` (first non-empty line is the value). A block is accepted
  only if the model's endpoint file in the Engine has that setting (and, for a
  list setting, that option); otherwise the file is rejected before any call.
  See `src/processing/setting_blocks.py`.
- `<!-- comments -->` are ignored. The parser is `src/processing/markdown_parser.py`.

## Profiles

A YAML profile in `USER-FILES/03.PROFILES/` says what to run: `platform`,
`endpoint`, `parameters` (`fps`, `duration`), `prompt_prefix`, `prompt_suffix`,
`pricing`, `paths`, and the slot keys `image_url_param`, `slots:`,
`duration_min` / `duration_max`. Engines seed examples into `USER-FILES/02.STANDBY/`;
copy one into `03.PROFILES/` to use it.

## Running

```bash
python run.py                       # standalone: 03.PROFILES → 04.INPUT → 05.OUTPUT
python run.py --dry-run             # validate, no calls
python run.py --cost-estimation     # estimate the cost, no calls
python -m src.main_verbose --profile P.yaml --input_dir IN --output_dir OUT   # as the Transceiver runs it
```

Output goes to `USER-FILES/05.OUTPUT/<YYMMDD_HHMMSS>_VID/`: each video with a
`.log` beside it, and on any failure a per-item `_ERROR.log` plus a run-level
`<YYMMDD_HHMMSS>_ERROR.log`.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) and [`ARCHITECTURE.md`](ARCHITECTURE.md).

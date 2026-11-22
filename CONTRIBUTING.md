# Contributing

Thanks for considering a contribution to the Video Generator, one of the
Generators Helmer runs through its Transceiver. Read
[`ARCHITECTURE.md`](ARCHITECTURE.md) first so you know where a change belongs.

## Setup

Python 3.10+ and a virtual environment:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

`python run.py` creates or repairs the venv itself, so it also works from a
clean checkout.

## Tests

```bash
python -m pytest tests -q
```

Tests are fast and hermetic: temporary directories, no network, no API keys.
Run the suite before every commit, and add or update a test for what you change.

## Conventions

- Python: type hints on function signatures, `pathlib.Path` for files, functions
  under ~50 lines, `black` and `ruff`.
- Fail loud: reject or report a problem rather than silently changing the
  user's intent.
- Never write into `USER-FILES/04.INPUT/`; outputs go to `USER-FILES/05.OUTPUT/`.
- Conventional commits (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`), one
  concern per pull request.

## Model endpoints

Model endpoints live in the Engine repos (`engine-*`) as TOML files, not here.

## Reporting bugs

Open an issue with the steps, what you expected, what happened (the
`_ERROR.log` from the output folder helps), and your OS and Python version.
For a generation bug include the Markdown file, the profile and the endpoint.

## License

See `LICENSE`. Contributions are licensed under the same terms.

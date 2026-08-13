"""
Vision-model log counting via the Gemini API, as a cross-check/alternative
to the pixel-signal-processing approach in log_count.py -- tried after
months of chasing background-structure false positives (fence, roof panel,
truss) that a model with semantic understanding of the scene shouldn't be
fooled by the way brightness-periodicity math is.

Not wired into the collector loop yet -- this is a standalone test module
to see how well it actually performs before deciding whether/how to
integrate it (e.g. as a periodic cross-check, or a tie-breaker when the two
log_count.py bands disagree).

Credentials live in ../secret/gemini.txt (KEY=VALUE per line: API_KEY plus
some account metadata), same pattern as every other credential here --
never hardcoded into a tracked source file, since this repo is pushed to a
public GitHub Pages site.

Usage: python gemini_counter.py <path-to-jpg> [<path-to-jpg> ...]
"""
import sys
from google import genai
from google.genai import types

_CREDENTIALS_PATH = "../secret/gemini.txt"

_PROMPT = """This photo is from a fixed security camera at an aluminum extrusion plant, looking down a "Log Pusher" table where cylindrical aluminum billets ("logs", each about 20 feet long, uniform grey color) are stored end-to-end in a row before being fed into a furnace queue.

Count ONLY the logs actually sitting on the table/rack in this row. Do not count:
- The diagonal orange-and-black safety fence in the foreground
- Roof/wall structure, trusses, or beams visible in the background
- Any other equipment, racks, or materials elsewhere in the frame
- A separate bundle of logs that may be staged off to the side, still banded/strapped together, not yet added to the row (if you can tell the difference)

Respond with ONLY a single integer -- the number of logs in the row. No other text."""


def _load_credentials():
    creds = {}
    with open(_CREDENTIALS_PATH) as f:
        for line in f:
            line = line.strip()
            if not line or "=" not in line:
                continue
            key, _, value = line.partition("=")
            creds[key.strip()] = value.strip()
    return creds


def count_logs_gemini(image_path, model="gemini-flash-latest"):
    """Sends the raw (unwarped) photo straight to Gemini and asks it to
    count -- deliberately NOT using log_count.py's perspective warp, since a
    general vision model should be given the scene in its natural form
    rather than a geometrically distorted crop it wasn't trained to expect.
    Returns (count, raw_response_text)."""
    creds = _load_credentials()
    client = genai.Client(api_key=creds["API_KEY"])

    with open(image_path, "rb") as f:
        image_bytes = f.read()

    response = client.models.generate_content(
        model=model,
        contents=[
            types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
            _PROMPT,
        ],
    )
    text = response.text.strip()

    try:
        count = int("".join(c for c in text if c.isdigit()))
    except ValueError:
        count = None

    return count, text


if __name__ == "__main__":
    for path in sys.argv[1:]:
        try:
            count, raw = count_logs_gemini(path)
            print(f"{path}: {count}  (raw response: {raw!r})")
        except Exception as e:
            print(f"{path}: FAILED -- {e}")

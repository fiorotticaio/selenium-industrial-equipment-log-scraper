# Industrial Equipment Log Scraper — Portfolio Project

A self-contained demo of a real-world "Data Foundry" style pipeline:
**Selenium extraction from a legacy-style portal → pandas curation →
clean, structured output.**

Because no company's real internal portal can ethically be scraped for a
portfolio piece, this project ships a small **mock legacy industrial
portal** (`mock_portal/`) that mimics the real thing: a login gate, three
pages of paginated equipment/maintenance records, and deliberately messy
HTML — mixed date formats, inconsistent casing, specs buried in a
data-attribute, missing fields, and duplicate records across pages. The
scraper and cleaner are written exactly as they would be against a real
target; only the target is synthetic.

## Architecture

```
mock_portal/generate_mock_portal.py   # builds the fake target site (run once)
mock_portal/site/                     # generated static HTML (login + 3 pages)
scraper.py                            # Selenium: login, paginate, extract raw fields
data_cleaner.py                       # pandas: normalize, dedupe, structure
main.py                               # orchestrates: serve site -> scrape -> clean -> save
output/                               # equipment_raw.json, equipment_cleaned.csv/json
```

**Why this split:** `scraper.py` only ever produces *raw, unopinionated*
strings — it doesn't try to parse dates or guess at units. `data_cleaner.py`
owns every normalization decision. That separation means the extraction
layer never breaks silently when a business rule changes (e.g. "we now
also count `retired` as `decommissioned`") — you touch one file, not two.

### Extraction design (`scraper.py`)
- **Explicit waits only** (`WebDriverWait` + `expected_conditions`) —
  no `time.sleep()`. Every action waits on a specific condition: element
  clickable, URL changed, table present.
- **Field-level error isolation** — each `<td>` is pulled in its own
  try/except. A single missing cell degrades to `None` for that field
  instead of losing the whole row, which matters a lot on real legacy
  markup that's rarely 100% consistent.
- **Pagination driven by the page, not an assumed count** — the loop
  clicks "Next" until the control is no longer a clickable link, so it
  survives the dataset growing or shrinking.
- **Selenium Manager** (built into Selenium 4.6+) resolves a matching
  chromedriver automatically — no manual driver downloads.

### Curation design (`data_cleaner.py`)
- **Status normalization** — `OPERATIONAL`, `Operational`, `operational`
  all collapse to one canonical value via a lookup map.
- **Multi-format date parsing** — tries `YYYY-MM-DD`, `DD/MM/YYYY`, and
  `Month D, YYYY` explicitly (rather than trusting pandas' generic
  inference, which can silently guess wrong on ambiguous `DD/MM` vs
  `MM/DD` strings), falling back to inference only as a logged last
  resort.
- **Semi-structured spec parsing** — the free-text
  `"Power: 50kW; Voltage: 480V; Type: X"` string is split into typed
  `power_kw`, `voltage_v`, `equipment_type` columns using independent
  regexes per field, so a missing field (e.g. no voltage listed) doesn't
  break extraction of the others.
- **Dedup with a completeness tiebreaker** — when the same
  `equipment_id` shows up on more than one page (a real artifact of
  paginated systems being re-sorted between loads), the most complete /
  most recent record wins instead of an arbitrary "first seen."
- **Review flagging, not silent drops** — rows missing a critical field
  are kept and flagged `needs_review=True` rather than discarded, so
  curation stays auditable.

## Setup & Run

```bash
pip install -r requirements.txt

# 1. Generate the mock target portal (one-time)
python mock_portal/generate_mock_portal.py

# 2. Run the full pipeline: serve portal -> scrape -> clean -> save
python main.py
```

Output lands in `output/`:
- `equipment_raw.json` — exactly what Selenium extracted, untouched
- `equipment_cleaned.csv` / `equipment_cleaned.json` — curated result

**Requirements to run locally:** a Chrome or Chromium installation (Selenium
Manager handles the driver). Runs headless by default — set
`headless=False` in `main.py`'s `scrape_all_pages(...)` call to watch it
drive the browser live, which is a nice thing to demo in an interview.

## Notes on realism vs. shortcuts

This is a portfolio artifact, so a couple of things are intentionally
simplified and worth naming up front if asked:
- Auth is a toy client-side check (`sessionStorage`), not a real
  session/cookie flow — in a production version, `login()` would instead
  assert on a server-set auth cookie or a redirect governed by the
  backend.
- The "legacy portal" is generated HTML, not a live third-party site —
  done deliberately, since scraping a real company's internal system
  without permission isn't something to demo.
- Everything else — the wait strategy, error isolation, pagination
  logic, and the cleaning pipeline — is written the way it would be
  against a real target.

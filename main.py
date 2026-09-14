"""
main.py
-------
End-to-end runner:
    1. Serves the mock portal locally (so the scraper has a real URL to hit).
    2. Runs the Selenium scraper against it (login -> paginate -> extract).
    3. Cleans the raw output with pandas.
    4. Writes both raw and cleaned data to /output as CSV + JSON.

Usage:
    python mock_portal/generate_mock_portal.py   # one-time, generates the site
    python main.py
"""

from __future__ import annotations

import http.server
import json
import logging
import os
import socketserver
import threading
import time

from data_cleaner import clean_pipeline
from scraper import records_to_dicts, scrape_all_pages

logger = logging.getLogger("company_scraper")

HERE = os.path.dirname(os.path.abspath(__file__))
SITE_DIR = os.path.join(HERE, "mock_portal", "site")
OUTPUT_DIR = os.path.join(HERE, "output")
PORT = 8000

LOGIN_USERNAME = "demo_engineer"
LOGIN_PASSWORD = "company2024"


def _serve_mock_site(port: int) -> socketserver.TCPServer:
    """Spin up a tiny local HTTP server for the mock portal in a background
    thread, so Selenium can navigate to real http:// URLs like it would
    against a real internal portal."""
    handler = lambda *args, **kwargs: http.server.SimpleHTTPRequestHandler(
        *args, directory=SITE_DIR, **kwargs
    )
    httpd = socketserver.TCPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd


def main() -> None:
    if not os.path.isdir(SITE_DIR):
        raise SystemExit(
            "Mock portal not found. Run "
            "`python mock_portal/generate_mock_portal.py` first."
        )
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    logger.info("Starting local server for mock portal on port %d", PORT)
    httpd = _serve_mock_site(PORT)
    time.sleep(0.3)  # give the server thread a moment to bind

    try:
        base_url = f"http://127.0.0.1:{PORT}"
        raw_records = scrape_all_pages(
            base_url=base_url,
            username=LOGIN_USERNAME,
            password=LOGIN_PASSWORD,
            headless=True,
        )

        raw_dicts = records_to_dicts(raw_records)
        raw_path = os.path.join(OUTPUT_DIR, "equipment_raw.json")
        with open(raw_path, "w", encoding="utf-8") as f:
            json.dump(raw_dicts, f, indent=2, default=str)
        logger.info("Raw scraped data written to %s", raw_path)

        cleaned_df = clean_pipeline(raw_dicts)

        cleaned_csv_path = os.path.join(OUTPUT_DIR, "equipment_cleaned.csv")
        cleaned_json_path = os.path.join(OUTPUT_DIR, "equipment_cleaned.json")
        cleaned_df.to_csv(cleaned_csv_path, index=False)
        cleaned_df.to_json(cleaned_json_path, orient="records", indent=2, date_format="iso")
        logger.info("Cleaned data written to %s and %s", cleaned_csv_path, cleaned_json_path)

        print("\n=== Summary ===")
        print(f"Raw records scraped:      {len(raw_dicts)}")
        print(f"Unique equipment records: {len(cleaned_df)}")
        print(f"Flagged for review:       {int(cleaned_df['needs_review'].sum())}")
        print("\nPreview:")
        print(cleaned_df.head(10).to_string(index=False))

    finally:
        httpd.shutdown()
        logger.info("Local mock portal server stopped")


if __name__ == "__main__":
    main()

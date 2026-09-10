"""
scraper.py
----------
Selenium-based extractor for the mock "MaintPortal Legacy" industrial
portal (see mock_portal/generate_mock_portal.py).

Design notes (this is the part worth explaining in an interview):

* Explicit waits only. No time.sleep() -- every interaction waits on a
  specific, named condition (element clickable, element present, table
  rows present) via WebDriverWait + expected_conditions. This is what
  makes a scraper survive a slow legacy portal instead of flaking under
  load.
* Field-level error isolation. Each field on a row is extracted in its
  own try/except so one malformed <td> (missing spec, empty date, a
  stray typo in a class name) degrades that single field to None instead
  of losing the entire row -- important on real legacy HTML where markup
  is rarely 100% consistent.
* Pagination is driven by the page, not by an assumed page count. The
  loop clicks "Next" until the link is gone / disabled, so it survives
  the underlying dataset growing or shrinking.
* Logging over print(). In a real pipeline this feeds observability
  tooling; here it also makes the extraction auditable during a demo.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from typing import Optional

from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
    ElementClickInterceptedException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.chrome.options import Options

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
)
logger = logging.getLogger("tractian_scraper")

DEFAULT_TIMEOUT = 10  # seconds, for every explicit wait


@dataclass
class EquipmentRecord:
    """One raw (still-messy) row scraped from the portal."""
    equipment_id: Optional[str]
    status: Optional[str]
    last_maintenance_raw: Optional[str]
    next_due_raw: Optional[str]
    specs_raw: Optional[str]
    location: Optional[str]
    source_page: int


def build_driver(headless: bool = True) -> webdriver.Chrome:
    """Configure and return a Chrome WebDriver instance.

    Uses Selenium 4's built-in Selenium Manager, so no manual chromedriver
    download/path management is required -- Selenium resolves a matching
    driver for whatever Chrome/Chromium is installed at runtime.
    """
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1400,1000")

    driver = webdriver.Chrome(options=options)
    driver.implicitly_wait(0)  # we use explicit waits exclusively -- no mixing
    return driver


def login(driver: webdriver.Chrome, base_url: str, username: str, password: str) -> None:
    """Authenticate against the mock portal's login form."""
    logger.info("Navigating to login page")
    driver.get(f"{base_url}/login.html")

    wait = WebDriverWait(driver, DEFAULT_TIMEOUT)
    user_field = wait.until(EC.presence_of_element_located((By.ID, "username")))
    pass_field = driver.find_element(By.ID, "password")
    login_button = wait.until(EC.element_to_be_clickable((By.ID, "loginButton")))

    user_field.clear()
    user_field.send_keys(username)
    pass_field.clear()
    pass_field.send_keys(password)

    try:
        login_button.click()
    except ElementClickInterceptedException:
        driver.execute_script("arguments[0].click();", login_button)

    # Wait for the redirect away from login.html to confirm success.
    wait.until(EC.url_contains("dashboard_page1.html"))
    logger.info("Login successful, landed on dashboard page 1")


def _extract_text(row, css_selector: str, field_name: str, row_id_hint: str) -> Optional[str]:
    """Safely pull text from a cell; log + return None rather than raising.

    Isolating each field like this means one bad/missing cell never takes
    down the whole row -- it just shows up as a null in the raw output,
    which is exactly what you want to see (and be able to trace) at the
    curation stage.
    """
    try:
        text = row.find_element(By.CSS_SELECTOR, css_selector).text.strip()
        return text if text else None
    except NoSuchElementException:
        logger.warning(
            "Missing field '%s' on row '%s' (selector: %s)",
            field_name, row_id_hint, css_selector,
        )
        return None


def _extract_specs(row, row_id_hint: str) -> Optional[str]:
    """Specs live in a data-attribute on the mock portal (a stand-in for
    the kind of tooltip/attribute-based semi-structured data you find on
    real legacy dashboards)."""
    try:
        specs_cell = row.find_element(By.CSS_SELECTOR, "td.specs")
        specs = specs_cell.get_attribute("data-specs")
        return specs.strip() if specs else None
    except NoSuchElementException:
        logger.warning("Missing specs cell on row '%s'", row_id_hint)
        return None


def scrape_current_page(driver: webdriver.Chrome, page_num: int) -> list[EquipmentRecord]:
    """Extract every equipment row on the currently-loaded page."""
    wait = WebDriverWait(driver, DEFAULT_TIMEOUT)
    wait.until(EC.presence_of_element_located((By.ID, "equipmentTable")))
    rows = driver.find_elements(By.CSS_SELECTOR, "tr.equip-row")
    logger.info("Page %d: found %d rows", page_num, len(rows))

    records = []
    for row in rows:
        equipment_id = _extract_text(row, "td.equip-id", "equipment_id", "unknown")
        record = EquipmentRecord(
            equipment_id=equipment_id,
            status=_extract_text(row, "td.status", "status", equipment_id or "unknown"),
            last_maintenance_raw=_extract_text(
                row, "td.last-maint", "last_maintenance", equipment_id or "unknown"
            ),
            next_due_raw=_extract_text(
                row, "td.next-due", "next_due", equipment_id or "unknown"
            ),
            specs_raw=_extract_specs(row, equipment_id or "unknown"),
            location=_extract_text(row, "td.location", "location", equipment_id or "unknown"),
            source_page=page_num,
        )
        records.append(record)
    return records


def go_to_next_page(driver: webdriver.Chrome) -> bool:
    """Click 'Next' if it's a real link; return False when pagination ends.

    The mock portal renders the disabled state as a <span id="nextPage">
    instead of an <a>, which mirrors how a lot of legacy pagers signal
    "no more pages" -- so we branch on tag name rather than assuming a
    fixed page count.
    """
    next_el = driver.find_element(By.ID, "nextPage")
    if next_el.tag_name.lower() != "a":
        logger.info("No further pages (pagination control is inactive)")
        return False

    wait = WebDriverWait(driver, DEFAULT_TIMEOUT)
    clickable_next = wait.until(EC.element_to_be_clickable((By.ID, "nextPage")))
    try:
        clickable_next.click()
    except ElementClickInterceptedException:
        driver.execute_script("arguments[0].click();", clickable_next)

    wait.until(EC.presence_of_element_located((By.ID, "equipmentTable")))
    return True


def scrape_all_pages(
    base_url: str,
    username: str,
    password: str,
    headless: bool = True,
    max_pages: int = 50,
) -> list[EquipmentRecord]:
    """End-to-end run: login, then walk every page collecting records."""
    driver = build_driver(headless=headless)
    all_records: list[EquipmentRecord] = []

    try:
        login(driver, base_url, username, password)

        page_num = 1
        while True:
            try:
                page_records = scrape_current_page(driver, page_num)
                all_records.extend(page_records)
            except TimeoutException:
                logger.error("Timed out waiting for table on page %d; stopping.", page_num)
                break

            if page_num >= max_pages:
                logger.warning("Hit max_pages=%d safety limit; stopping.", max_pages)
                break

            has_next = go_to_next_page(driver)
            if not has_next:
                break
            page_num += 1

    finally:
        driver.quit()
        logger.info("Driver closed. Total raw records scraped: %d", len(all_records))

    return all_records


def records_to_dicts(records: list[EquipmentRecord]) -> list[dict]:
    return [asdict(r) for r in records]

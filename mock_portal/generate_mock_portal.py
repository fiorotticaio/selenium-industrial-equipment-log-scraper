"""
generate_mock_portal.py
------------------------
Generates a small, self-contained "legacy industrial portal" made of static
HTML pages: a login screen + a paginated equipment/maintenance log table.

This exists ONLY so the Selenium scraper has a realistic, messy, semi-
structured target to run against locally (no real company's site is
scraped). The HTML is intentionally inconsistent -- mixed date formats,
mixed-case statuses, specs buried in a data-attribute, occasional missing
fields, and a couple of duplicate rows across pages -- to mirror what a
real 10+ year old maintenance portal tends to look like.

Run this once before running scraper.py:
    python mock_portal/generate_mock_portal.py
"""

import os

SITE_DIR = os.path.join(os.path.dirname(__file__), "site")

LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>MaintPortal Legacy - Login</title>
</head>
<body>
    <h1>MaintPortal Legacy System</h1>
    <form id="loginForm">
        <label for="username">Username</label>
        <input type="text" id="username" name="username">
        <label for="password">Password</label>
        <input type="password" id="password" name="password">
        <button type="button" id="loginButton" onclick="doLogin()">Login</button>
        <p id="loginError" style="color:red; display:none;">Invalid credentials</p>
    </form>

    <script>
        function doLogin() {
            var user = document.getElementById('username').value;
            var pass = document.getElementById('password').value;
            // Toy client-side auth check purely to simulate a gated legacy portal.
            if (user === 'demo_engineer' && pass === 'Tractian2024') {
                sessionStorage.setItem('authenticated', 'true');
                window.location.href = 'dashboard_page1.html';
            } else {
                document.getElementById('loginError').style.display = 'block';
            }
        }
    </script>
</body>
</html>
"""

# Each "guard" script below simply bounces unauthenticated visitors back to
# the login page, the way a lot of legacy portals do with server-side
# session checks -- here faked client-side since this is a static mock.
GUARD_SCRIPT = """
    <script>
        if (sessionStorage.getItem('authenticated') !== 'true') {
            window.location.href = 'login.html';
        }
    </script>
"""

# (equipment_id, status, last_maintenance, next_due, specs_attr, location)
# Deliberately messy: mixed case/format, some duplicates across pages,
# and a couple of rows with a field missing entirely to exercise error
# handling in the scraper.
PAGE_1_ROWS = [
    ("EQX-1042", "OPERATIONAL", "2024-03-15", "2024-09-15",
     "Power: 50kW; Voltage: 480V; Type: Induction Motor", "Plant A - Line 3"),
    ("EQX-1043", "under_maintenance", "15/01/2024", "15/07/2024",
     "Power: 12kW; Voltage: 220V; Type: Conveyor Drive", "Plant A - Line 1"),
    ("EQX-1044", "Operational", "March 2, 2024", "September 2, 2024",
     "Power: 75kW; Voltage: 480V; Type: Compressor", "Plant B - Bay 2"),
    ("EQX-1045", "OFFLINE", "", "",
     "Power: 30kW; Voltage: 380V; Type: Pump", "Plant A - Line 2"),
    ("EQX-1046", "operational", "2024-02-28", "2024-08-28",
     "Power: 5kW; Voltage: 220V; Type: Sensor Array", "Plant C - Zone 1"),
]

PAGE_2_ROWS = [
    ("EQX-1047", "Under Maintenance", "01-04-2024", "01-10-2024",
     "Power: 90kW; Voltage: 480V; Type: Hydraulic Press", "Plant B - Bay 4"),
    ("EQX-1044", "Operational", "March 2, 2024", "September 2, 2024",   # duplicate of page 1
     "Power: 75kW; Voltage: 480V; Type: Compressor", "Plant B - Bay 2"),
    ("EQX-1048", "OPERATIONAL", "2024-04-10", "2024-10-10",
     "Power: 18kW; Type: Conveyor Drive", "Plant A - Line 3"),  # missing voltage on purpose
    ("EQX-1049", "decommissioned", "2023-11-01", "N/A",
     "Power: 60kW; Voltage: 480V; Type: Compressor", "Plant B - Bay 1"),
    ("EQX-1050", "Operational", "10/05/2024", "10/11/2024",
     "Power: 22kW; Voltage: 380V; Type: Pump", "Plant C - Zone 2"),
]

PAGE_3_ROWS = [
    ("EQX-1051", "OPERATIONAL", "2024-05-20", "2024-11-20",
     "Power: 45kW; Voltage: 480V; Type: Induction Motor", "Plant A - Line 4"),
    ("EQX-1052", "under_maintenance", "May 22, 2024", "November 22, 2024",
     "Power: 8kW; Voltage: 220V; Type: Sensor Array", "Plant C - Zone 1"),
    ("EQX-1042", "OPERATIONAL", "2024-03-15", "2024-09-15",   # duplicate of page 1
     "Power: 50kW; Voltage: 480V; Type: Induction Motor", "Plant A - Line 3"),
]


def _row_html(row):
    equipment_id, status, last_maint, next_due, specs, location = row
    return f"""
        <tr class="equip-row">
            <td class="equip-id">{equipment_id}</td>
            <td class="status">{status}</td>
            <td class="last-maint">{last_maint}</td>
            <td class="next-due">{next_due}</td>
            <td class="specs" data-specs="{specs}">
                <span class="specs-tooltip">{specs}</span>
            </td>
            <td class="location">{location}</td>
        </tr>"""


def _page_html(rows, page_num, total_pages):
    rows_html = "\n".join(_row_html(r) for r in rows)

    prev_link = (
        f'<a href="dashboard_page{page_num - 1}.html" id="prevPage">&laquo; Prev</a>'
        if page_num > 1 else '<span id="prevPage">&laquo; Prev</span>'
    )
    next_link = (
        f'<a href="dashboard_page{page_num + 1}.html" id="nextPage">Next &raquo;</a>'
        if page_num < total_pages else '<span id="nextPage">Next &raquo;</span>'
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>MaintPortal Legacy - Equipment Log (Page {page_num})</title>
</head>
<body>
{GUARD_SCRIPT}
    <h1>Equipment &amp; Maintenance Log</h1>
    <p>Page {page_num} of {total_pages}</p>
    <table id="equipmentTable">
        <thead>
            <tr>
                <th>Equipment ID</th>
                <th>Status</th>
                <th>Last Maintenance</th>
                <th>Next Due</th>
                <th>Technical Specs</th>
                <th>Location</th>
            </tr>
        </thead>
        <tbody>
{rows_html}
        </tbody>
    </table>
    <div class="pagination">
        {prev_link}
        <span id="currentPage">{page_num}</span>
        {next_link}
    </div>
    <p><a href="login.html" onclick="sessionStorage.removeItem('authenticated')">Logout</a></p>
</body>
</html>
"""


def generate_site():
    os.makedirs(SITE_DIR, exist_ok=True)

    with open(os.path.join(SITE_DIR, "login.html"), "w", encoding="utf-8") as f:
        f.write(LOGIN_HTML)

    pages = [PAGE_1_ROWS, PAGE_2_ROWS, PAGE_3_ROWS]
    total_pages = len(pages)
    for idx, rows in enumerate(pages, start=1):
        path = os.path.join(SITE_DIR, f"dashboard_page{idx}.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(_page_html(rows, idx, total_pages))

    print(f"Mock portal generated at: {SITE_DIR}")
    print(f"  - login.html")
    for idx in range(1, total_pages + 1):
        print(f"  - dashboard_page{idx}.html")


if __name__ == "__main__":
    generate_site()

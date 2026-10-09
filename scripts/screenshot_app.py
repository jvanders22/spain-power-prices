"""Screenshot the running dashboard for the README.

Start the app first (`streamlit run app/streamlit_app.py --server.port 8599`), then run
`python scripts/screenshot_app.py`. Needs `pip install playwright` and a Chrome/Chromium
(set CHROME to its path, default /usr/bin/google-chrome).
"""

import os

from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    b = p.chromium.launch(
        executable_path=os.environ.get("CHROME", "/usr/bin/google-chrome"), args=["--no-sandbox"]
    )
    pg = b.new_page(viewport={"width": 1400, "height": 1000}, device_scale_factor=1.5)
    pg.goto("http://localhost:8599", wait_until="networkidle")
    pg.wait_for_selector("[data-testid='stMetric']", timeout=60000)
    pg.wait_for_timeout(5000)
    pg.screenshot(path="docs/img/dashboard.png", full_page=True)
    pg.get_by_role("tab", name="Zero/negative hours").click()
    pg.wait_for_timeout(4000)
    pg.screenshot(path="docs/img/dashboard_heatmap_tab.png", full_page=True)
    b.close()

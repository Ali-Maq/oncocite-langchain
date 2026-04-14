"""
End-to-end Playwright test against the live OncoCITE demo.

Verifies the full reviewer experience: loads the landing page, dismisses
it, clicks a paper from the sidebar, opens the PDF viewer pane, and
confirms the PDF actually renders. Captures every network request and
console message so any regression is immediately diagnosable.

Runs against https://13-217-205-13.sslip.io/ (the live demo referenced in
Supplementary Figure S5 / the paper, served over HTTPS via Let's Encrypt
with a 301 redirect from the raw-IP URL in the paper).

Install + run:
    uv sync --group dev
    uv run playwright install chromium
    uv run pytest tests/test_e2e_demo.py -v
"""

from __future__ import annotations

import pytest
from playwright.async_api import async_playwright

DEMO_URL = "https://13-217-205-13.sslip.io/"


@pytest.mark.asyncio
async def test_demo_loads_and_renders_paper() -> None:
    """Click a paper from the sidebar, open the PDF viewer, confirm it renders."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(ignore_https_errors=True)
        page = await context.new_page()

        console_messages: list[tuple[str, str]] = []
        page_errors: list[str] = []

        page.on("console", lambda m: console_messages.append((m.type, m.text)))
        page.on("pageerror", lambda e: page_errors.append(str(e)))

        # Load landing page
        await page.goto(DEMO_URL, timeout=60_000, wait_until="networkidle")
        assert "OncoCITE" in await page.title()

        # Dismiss landing overlay
        try:
            await page.locator("text=Get Started").first.click(timeout=5_000)
        except Exception:
            pass
        await page.wait_for_timeout(2_000)

        # Click a small paper to minimise flakiness
        await page.locator("text=PMID 18528420").first.click(timeout=5_000)
        await page.wait_for_timeout(2_000)

        # Toggle the PDF viewer pane
        await page.locator("text=Original PDF").first.click(timeout=5_000)
        await page.wait_for_timeout(10_000)

        # Evidence the PDF actually rendered
        canvas_count = await page.locator(".react-pdf__Page__canvas").count()
        assert canvas_count >= 1, "PDF.js canvas did not render"

        # No uncaught JS errors across the whole flow
        assert not page_errors, f"Uncaught JS errors: {page_errors}"

        # No ERROR-level console messages besides known benign ones
        hard_errors = [
            (lvl, msg) for lvl, msg in console_messages
            if lvl == "error" and "ERR_ABORTED" not in msg
        ]
        assert not hard_errors, f"Hard console errors: {hard_errors}"

        await browser.close()

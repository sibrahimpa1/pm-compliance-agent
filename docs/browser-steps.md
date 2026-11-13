# Browser steps (tier 3)

Some Buildium changes have no API field and no bulk update, for example a
"do not dispatch" hold on a vendor or a licence expiry kept in a custom field.
For those the audit does not drive a browser. It queues a `buildium_change`
item with `channel = browser_step`, the exact field, the current value, the new
value and the reason. Nothing happens until a person approves it.

After approval, an operator (or a supervised script) applies the change, and
the next audit reads the value back through the API or a fresh export.
`BuildiumAdapter.verify_readback()` marks the change done only when the value
read back equals the value that was approved.

## Example Playwright step

Selectors and paths below are placeholders. In a pilot they are recorded
against the client's own account (`playwright codegen`) and kept in one file
so a UI change breaks one place.

```python
# pip install playwright && playwright install chromium
from playwright.sync_api import sync_playwright

BASE_URL = "https://<your-account>.managebuilding.com"  # placeholder


def set_vendor_do_not_dispatch(page, vendor_name: str) -> None:
    page.goto(BASE_URL + "/manager/vendors")  # placeholder path
    page.get_by_placeholder("Search").fill(vendor_name)
    page.get_by_role("link", name=vendor_name).click()
    page.get_by_role("button", name="Edit").click()
    page.get_by_label("Do not dispatch").check()  # custom field label, placeholder
    page.screenshot(path="before-save.png")
    page.get_by_role("button", name="Save").click()
    page.screenshot(path="after-save.png")


def run(approved_item: dict) -> None:
    """Only ever called with a queue item whose status is 'approved'."""
    assert approved_item["status"] == "approved"
    payload = approved_item["payload"]
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # a person watches the first runs
        context = browser.new_context(storage_state="buildium-session.json")  # signed in by a person
        page = context.new_page()
        if payload["playwright_step"] == "set_vendor_do_not_dispatch":
            set_vendor_do_not_dispatch(page, payload["entity_name"])
        browser.close()
```

Rules that go with it:

- The script never signs in by itself; a person signs in and saves the session.
- One approved item, one change. No loops over the whole vendor list.
- Before and after screenshots go into the audit trail.
- The change counts as done only after the read-back matches.

import time
import re
from typing import List, Dict, Optional, Tuple

from appium import webdriver
from appium.options.android import UiAutomator2Options
from appium.webdriver.common.appiumby import AppiumBy

# Keywords we want to keep and try to open. Everything else gets dismissed.
IMPORTANT_KEYWORDS = ["bank", "security", "delivery"]
IMPORTANT_KEYWORDS = [k.lower() for k in IMPORTANT_KEYWORDS]

# Loop safety limits
MAX_DISMISS_ACTIONS = 40 # prevents infinite dismissal loops
MAX_SCROLLS_NO_PROGRESS = 4  # stop after n scrolls without dismissing anything

# timing and waits
SWIPE_DURATION_MS = 650
DISMISS_SWIPE_MS = 350
UI_RENDER_SLEEP_SHORT = 0.15
UI_RENDER_SLEEP_MED = 0.35

# xml parsing
MIN_NODE_AREA = 15000 # set to ignore very small text ex. icons
KEYWORD_TEXT_WEIGHT = 400 # scoring boost for longer text 


Rect = Tuple[int, int, int, int]  #(x1, y1, x2, y2)

# Gesture helpers
def swipe_down(driver, times: int = 1) -> None:
    """
    Pull down the notification shade.
    Swipe from near the top of the screen to about 75% down to open shade. Sleeps after each swipe to let UI animations finish
    """
    size = driver.get_window_size()
    x = size["width"] // 2
    start_y = int(size["height"] * 0.03)
    end_y = int(size["height"] * 0.75)

    for _ in range(times):
        driver.swipe(x, start_y, x, end_y, SWIPE_DURATION_MS)
        time.sleep(UI_RENDER_SLEEP_MED)

def swipe_up(driver, times: int = 1) -> None:
    """
    Scroll the notification list upward

    Gives ability to scan through list of notifications when there no dismissable rows
    """
    size = driver.get_window_size()
    x = size["width"] // 2
    start_y = int(size["height"] * 0.75)
    end_y = int(size["height"] * 0.20)

    for _ in range(times):
        driver.swipe(x, start_y, x, end_y, SWIPE_DURATION_MS)
        time.sleep(0.25)

def click_xy(driver, x: int, y: int) -> None:
    """
    Tap a screen coordinate.
    """
    driver.execute_script("mobile: tapGesture", {"x": int(x), "y": int(y)})


def swipe_left_on_element(driver, el) -> None:
    """
    Dismiss notification by swiping left across its row element
    """
    r = el.rect
    start_x = int(r["x"] + r["width"] * 0.90)
    end_x = int(r["x"] + r["width"] * 0.10)
    y = int(r["y"] + r["height"] * 0.50)

    driver.swipe(start_x, y, end_x, y, DISMISS_SWIPE_MS)

# Geometry helpers

def parse_bounds(bounds_str: str) -> Optional[Rect]:
    """
    Parse Android bounds like [x1,y1][x2,y2] into a tuple (x1, y1, x2, y2)

    Returns:
        Rect tuple if parsing succeeds, otherwise None
    """
    nums = list(map(int, re.findall(r"\d+", bounds_str or "")))
    if len(nums) != 4:
        return None
    return nums[0], nums[1], nums[2], nums[3]


def overlap_area(a: Rect, b: Rect) -> int:
    """
    Compute intersection area between two rectangles (x1,y1,x2,y2)

    assigns xml text nodes to the most likely notification row by geometric overlap
    """
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b

    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)

    if ix2 <= ix1 or iy2 <= iy1:
        return 0
    return (ix2 - ix1) * (iy2 - iy1)


def rect_tuple_from_el(el) -> Rect:
    """
    Convert an element's rect dict to (x1, y1, x2, y2)
    """
    r = el.rect
    return (r["x"], r["y"], r["x"] + r["width"], r["y"] + r["height"])

# Map notification rows to text using xml overlap

def build_rows_with_text(xml: str) -> List[Dict]:
    """
    Build a list of notification rows with text using page_source xml 
    """
    # Find notification row bounds
    row_bounds = re.findall(
        r'resource-id="[^"]*expandableNotificationRow[^"]*".*?bounds="(\[[^\]]+\]\[[^\]]+\])"',
        xml
    )

    rows: List[Dict] = []
    for bstr in row_bounds:
        btup = parse_bounds(bstr)
        if btup:
            rows.append({"bounds": btup, "text": ""})

    if not rows:
        return []

    # Find any node that has visible text or accessibility text & bounds
    node_matches = re.findall(
        r'(?:text|content-desc)="([^"]+)"[^>]*bounds="(\[[^\]]+\]\[[^\]]+\])"',
        xml
    )

    # Assign each text node to the best-overlapping notification row
    for val, bstr in node_matches:
        btup = parse_bounds(bstr)
        if not btup:
            continue

        v = (val or "").strip()
        if not v:
            continue

        best_i: Optional[int] = None
        best_oa = 0

        for i, row in enumerate(rows):
            oa = overlap_area(btup, row["bounds"])
            if oa > best_oa:
                best_oa = oa
                best_i = i

        if best_i is not None and best_oa > 0:
            rows[best_i]["text"] += " " + v

    # uniform text
    for row in rows:
        row["text"] = " ".join(row["text"].split()).lower()

    return rows


def best_row_text_for_element(el, rows_with_text: List[Dict]) -> str:
    """
    Return mapped XML text for the most-overlapping row
    """
    et = rect_tuple_from_el(el)
    best_text = ""
    best_oa = 0

    for row in rows_with_text:
        oa = overlap_area(et, row["bounds"])
        if oa > best_oa:
            best_oa = oa
            best_text = row["text"]

    return best_text or ""

# Expand grouped notifs

def expand_groups_if_present(driver) -> None:
    """
    Expand grouped notifications so more rows are visible
    """
    selectors = [
        'new UiSelector().descriptionContains("Expand")',
        'new UiSelector().descriptionContains("expand")',
        'new UiSelector().descriptionContains("More")',
        'new UiSelector().descriptionContains("more")',
        'new UiSelector().textContains("Expand")',
        'new UiSelector().textContains("More")',
    ]

    for sel in selectors:
        try:
            els = driver.find_elements(AppiumBy.ANDROID_UIAUTOMATOR, sel)
            for el in els[:2]:  # limit taps to not expand unrelated UI
                try:
                    el.click()
                    time.sleep(UI_RENDER_SLEEP_SHORT)
                except Exception:
                    # Expand controls are sometimes not clickable due to overlays/animation
                    pass
        except Exception:
            # Element search can throw if the UI tree changes mid-scan
            pass


# Extract text per row

def extract_row_text(driver, row_el, rows_with_text: List[Dict]) -> str:
    """
    Return normalized text describing a notification row
    """
    parts: List[str] = []

    # Collect visible text nodes under this row
    try:
        text_nodes = row_el.find_elements(AppiumBy.XPATH, ".//*[@text]")
        for n in text_nodes[:25]:
            try:
                t = (n.get_attribute("text") or "").strip()
                if t:
                    parts.append(t)
            except Exception:
                pass
    except Exception:
        pass

    # Collect accessibility text nodes under this row
    try:
        cd_nodes = row_el.find_elements(AppiumBy.XPATH, ".//*[@content-desc]")
        for n in cd_nodes[:25]:
            try:
                cd = (n.get_attribute("content-desc") or "").strip()
                if cd:
                    parts.append(cd)
            except Exception:
                pass
    except Exception:
        pass

    row_text = " ".join(parts).strip().lower()

    # Fallback --> use XML mapping if the element tree doesn't give us any text
    if not row_text:
        try:
            row_text = best_row_text_for_element(row_el, rows_with_text)
        except Exception:
            row_text = ""

    # Normalize whitespace and case
    return " ".join(row_text.split()).lower()


def is_important_row_text(row_text: str, important_keywords: List[str]) -> bool:
    """
    True if any keyword appears in the row text. keywords expected to be lowercased
    """
    rt = row_text or ""
    return any(k in rt for k in important_keywords)

# Opening a notification by keyword

def find_best_keyword_node(xml: str, keywords_lower: List[str]) -> Tuple[Optional[Rect], Optional[str]]:
    """
    Find most relevant xml node containing any keyword. Used as fallback for opening a notification when standard element clicks fail
    """
    pattern = r'(?:text|content-desc)="([^"]+)"[^>]*bounds="(\[[^\]]+\]\[[^\]]+\])"'
    candidates: List[Tuple[int, str, Rect]] = []

    for m in re.finditer(pattern, xml):
        raw = (m.group(1) or "").strip()
        val = raw.lower()
        b = parse_bounds(m.group(2))

        if not val or not b:
            continue

        if not any(k in val for k in keywords_lower):
            continue

        # Skip nodes that are too small
        x1, y1, x2, y2 = b
        area = max(0, x2 - x1) * max(0, y2 - y1)
        if area < MIN_NODE_AREA:
            continue

        # Prioritize larger nodes with longer text
        score = area + (len(val) * KEYWORD_TEXT_WEIGHT)
        candidates.append((score, val, b))

    if not candidates:
        return None, None

    candidates.sort(key=lambda x: x[0], reverse=True)
    best_score, best_text, best_bounds = candidates[0]
    return best_bounds, best_text


def open_notification_by_keyword(driver, keyword: str) -> bool:
    """
    Trys to open a notification that contains keyword --> Returns True if current opened app changes meaning a notification opened.
    """
    kw = keyword.lower()
    before_pkg = driver.current_package

    # direct UiAutomator text search
    try:
        el = driver.find_element(
            AppiumBy.ANDROID_UIAUTOMATOR,
            f'new UiSelector().textContains("{kw}")'
        )
        el.click()
        time.sleep(2.0)
        if driver.current_package != before_pkg:
            return True
    except Exception:
        pass

    # XPath keyword search -> click nearest clickable ancestor
    try:
        U = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        L = "abcdefghijklmnopqrstuvwxyz"
        parent = driver.find_element(
            AppiumBy.XPATH,
            f'//*[contains(translate(@text, "{U}", "{L}"), "{kw}") '
            f' or contains(translate(@content-desc, "{U}", "{L}"), "{kw}")]'
            f'/ancestor::*[@clickable="true"][1]'
        )
        parent.click()
        time.sleep(2.0)
        if driver.current_package != before_pkg:
            return True
    except Exception:
        pass

    # If other don't work, falls back by parsing XML bounds and tapping coordinate
    try:
        xml = driver.page_source
        b, _txt = find_best_keyword_node(xml, [kw])
        if b:
            x1, y1, x2, y2 = b
            cy = (y1 + y2) // 2
            # Offset into the row to avoid tapping action buttons such as "Clear" or "Reply"
            cx = max(10, x1 - 80)
            click_xy(driver, cx, cy)

            time.sleep(2.0)
            if driver.current_package != before_pkg:
                return True
    except Exception:
        pass

    return False


def find_row_elements(driver):
    """
    Return elements that correspond to actual notification rows
    """
    return driver.find_elements(
        AppiumBy.ANDROID_UIAUTOMATOR,
        'new UiSelector().resourceIdMatches(".*expandableNotificationRow.*")'
    )

# Main script logic

# Notification clearing and opening workflow
opts = UiAutomator2Options()
opts.platform_name = "Android"
opts.device_name = "Android Emulator"
opts.automation_name = "UiAutomator2"

# connect to the running Appium server
driver = webdriver.Remote("http://127.0.0.1:4723", options=opts)

try:
    # open notification shade and expand groups so row text is visible
    swipe_down(driver, times=2)
    time.sleep(0.4)
    expand_groups_if_present(driver)

    # dismiss everything not important
    print("Clearing non-important notifications")

    dismiss_actions = 0
    scrolls_without_dismiss = 0

    while dismiss_actions < MAX_DISMISS_ACTIONS and scrolls_without_dismiss < MAX_SCROLLS_NO_PROGRESS:
        # build XML mapping of rows -> text 
        xml = driver.page_source
        rows_with_text = build_rows_with_text(xml)

        # current visible rows
        row_elements = find_row_elements(driver)
        if not row_elements:
            break

        dismissed_this_round = False

        # Work top-down. after swipe, refresh UI to avoid old element references
        for row_el in row_elements[:10]:
            row_text = extract_row_text(driver, row_el, rows_with_text)

            # Keep important notifications
            if is_important_row_text(row_text, IMPORTANT_KEYWORDS):
                continue

            # Dismiss anything non-important & unreadable(some may be unreadable because I created empty notifications through cmd for testing, so nothing to click and open even if important)
            print(f"  [dismiss] {(row_text[:120] if row_text else '<unreadable>')}")
            try:
                swipe_left_on_element(driver, row_el)
                time.sleep(0.25)
                dismiss_actions += 1
                dismissed_this_round = True
            except Exception:
                pass

            # After one swipe, break to prevent old element errors
            break

        if dismissed_this_round:
            scrolls_without_dismiss = 0
            expand_groups_if_present(driver)
            continue

        # no dismissals this round -> scroll to reveal more notifications
        swipe_up(driver, times=1)
        time.sleep(0.2)
        expand_groups_if_present(driver)
        scrolls_without_dismiss += 1

    # open first openable important notification
    print("Opening first openable important notification and ending inside app")

    # bring shade back to top before attempting to open
    swipe_down(driver, times=2)
    time.sleep(0.4)
    expand_groups_if_present(driver)

    opened_pkg = None

    # Keywords tried in order and stops after first successful open
    for kw in IMPORTANT_KEYWORDS:
        print(f"Trying to open notification containing: {kw}")
        if open_notification_by_keyword(driver, kw):
            opened_pkg = driver.current_package
            print(f"Opened app package: {opened_pkg}")
            break

    if not opened_pkg:
        print("No important notification opened (none present or not openable)")

finally:
    driver.quit()

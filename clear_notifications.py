import time
import re
from appium import webdriver
from appium.options.android import UiAutomator2Options
from appium.webdriver.common.appiumby import AppiumBy

# Gestures helpers
def swipe_down(driver, times=1):
    """Pull down the notification shade"""
    size = driver.get_window_size()
    x = size["width"] // 2
    start_y = int(size["height"] * 0.03)
    end_y = int(size["height"] * 0.75)
    for _ in range(times):
        driver.swipe(x, start_y, x, end_y, 650)
        time.sleep(0.35)  # Pause for UI rendering

def swipe_up(driver, times=1):
    """Scroll the notification list upward"""
    size = driver.get_window_size()
    x = size["width"] // 2
    start_y = int(size["height"] * 0.75)
    end_y = int(size["height"] * 0.20)
    for _ in range(times):
        driver.swipe(x, start_y, x, end_y, 650)
        time.sleep(0.25)


def click_xy(driver, x, y):
    """Tap a screen coordinate"""
    driver.execute_script("mobile: tapGesture", {"x": int(x), "y": int(y)})


def swipe_left_on_element(driver, el):
    """Dismiss notification by swiping left across its row element"""
    r = el.rect
    start_x = int(r["x"] + r["width"] * 0.90)
    end_x = int(r["x"] + r["width"] * 0.10)
    y = int(r["y"] + r["height"] * 0.50)
    driver.swipe(start_x, y, end_x, y, 350)

# Geometry helpers

def parse_bounds(bounds_str: str):
    """Parse Android bounds like [x1,y1][x2,y2] into a tuple (x1,y1,x2,y2)"""
    nums = list(map(int, re.findall(r"\d+", bounds_str or "")))
    if len(nums) != 4:
        return None
    return nums[0], nums[1], nums[2], nums[3]


def overlap_area(a, b) -> int:
    """Intersection area between two rectangles (x1,y1,x2,y2)"""
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0
    return (ix2 - ix1) * (iy2 - iy1)


def rect_tuple_from_el(el):
    """Convert rect dict to (x1,y1,x2,y2)"""
    r = el.rect
    return (r["x"], r["y"], r["x"] + r["width"], r["y"] + r["height"])

# Map notification rows to text with XML overlap
def build_rows_with_text(xml: str):
    """ Build a list of notification rows with text using page_source XML """
    # Find notif row bounds
    row_bounds = re.findall(
        r'resource-id="[^"]*expandableNotificationRow[^"]*".*?bounds="(\[[^\]]+\]\[[^\]]+\])"',
        xml
    )

    rows = []
    for bstr in row_bounds:
        btup = parse_bounds(bstr)
        if btup:
            rows.append({"bounds": btup, "text": ""})

    if not rows:
        return []

    #Find any node that has visible text or accessibility text & bounds
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

        best_i = None
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


def best_row_text_for_element(el, rows_with_text):
    """Return mapped XML text for the most overlapping row"""
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
def expand_groups_if_present(driver):
    """Exapnd notifs so rows are visible"""
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
                    time.sleep(0.15)
                except Exception:
                    pass
        except Exception:
            pass

# Extract text per row
def extract_row_text(driver, row_el, rows_with_text):
    """Return normalized text describing a notification row"""
    parts = []

    try:
        desc_text_nodes = row_el.find_elements(AppiumBy.XPATH, ".//*[@text]")
        for n in desc_text_nodes[:25]:
            try:
                t = (n.get_attribute("text") or "").strip()
                if t:
                    parts.append(t)
            except Exception:
                pass
    except Exception:
        pass

    try:
        desc_cd_nodes = row_el.find_elements(AppiumBy.XPATH, ".//*[@content-desc]")
        for n in desc_cd_nodes[:25]:
            try:
                cd = (n.get_attribute("content-desc") or "").strip()
                if cd:
                    parts.append(cd)
            except Exception:
                pass
    except Exception:
        pass

    row_text = " ".join(parts).strip().lower()

    # use XML mapping for this row element
    if not row_text:
        try:
            row_text = best_row_text_for_element(row_el, rows_with_text)
        except Exception:
            row_text = ""

    # Normalize whitespace and case
    return " ".join(row_text.split()).lower()


def is_important_row_text(row_text: str, important_keywords):
    """True if any keyword appears in the notification row text"""
    return any(k in (row_text or "") for k in important_keywords)

# Open a notification by keyword

def find_best_keyword_node(xml: str, keywords_lower):
    """find most relevant node containing any keyword"""
    pattern = r'(?:text|content-desc)="([^"]+)"[^>]*bounds="(\[[^\]]+\]\[[^\]]+\])"'
    candidates = []

    for m in re.finditer(pattern, xml):
        raw = (m.group(1) or "").strip()
        val = raw.lower()
        b = parse_bounds(m.group(2))
        if not val or not b:
            continue

        if not any(k in val for k in keywords_lower):
            continue

        # Skip nodes that are too small, since likely not notification content
        x1, y1, x2, y2 = b
        area = max(0, x2 - x1) * max(0, y2 - y1)
        if area < 15000:
            continue

        # Prioritize larger nodes with longer text
        score = area + (len(val) * 400)
        candidates.append((score, val, b))

    if not candidates:
        return None, None

    candidates.sort(key=lambda x: x[0], reverse=True)
    best = candidates[0]
    return best[2], best[1]


def open_notification_by_keyword(driver, keyword: str) -> bool:
    """Trys to open a notification that contains keyword --> Returns True if current opened app changes meaning a notification opened."""
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

    # XPath keyword search --> click nearest clickable ancestor
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
            cx = max(10, x1 - 80)  # offset into the notification row to avoid hitting buttons
            click_xy(driver, cx, cy)
            time.sleep(2.0)
            if driver.current_package != before_pkg:
                return True
    except Exception:
        pass

    return False


def find_row_elements(driver):
    """Return elements that correspond to actual notification rows"""
    return driver.find_elements(
        AppiumBy.ANDROID_UIAUTOMATOR,
        'new UiSelector().resourceIdMatches(".*expandableNotificationRow.*")'
    )

# Notification clearing and opening workflow

opts = UiAutomator2Options()
opts.platform_name = "Android"
opts.device_name = "Android Emulator"
opts.automation_name = "UiAutomator2"

driver = webdriver.Remote("http://127.0.0.1:4723", options=opts)

try:
    # Keywords we want to keep and open --> all others get cleared
    IMPORTANT_KEYWORDS = ["bank", "security", "delivery"]
    IMPORTANT_KEYWORDS = [k.lower() for k in IMPORTANT_KEYWORDS]

    # Open notification shade and expand groups so row text is visible
    swipe_down(driver, times=2)
    time.sleep(0.4)
    expand_groups_if_present(driver)

    # Dismiss everything not important

    print("Clearing non-important notifications")

    dismiss_actions = 0
    max_dismiss_actions = 40 # Avoid infinite loops
    scrolls_without_dismiss = 0 # stop after several scrolls with no progress

    while dismiss_actions < max_dismiss_actions and scrolls_without_dismiss < 4:
        # Build XML mapping of rows to text
        xml = driver.page_source
        rows_with_text = build_rows_with_text(xml)

        # Current visible rows
        row_elements = find_row_elements(driver)
        if not row_elements:
            break

        dismissed_this_round = False

        # Work top-down; if dismissal occurs UI is refreshed to avoid old element references
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

        # Scrolls to reveal more notifications
        swipe_up(driver, times=1)
        time.sleep(0.2)
        expand_groups_if_present(driver)
        scrolls_without_dismiss += 1

    # Open the first openable important notification

    print("Opening first openable important notification and ends inside app")

    # Open shade at the top before attempting to open
    swipe_down(driver, times=2)
    time.sleep(0.4)
    expand_groups_if_present(driver)

    before_pkg = driver.current_package
    opened_pkg = None

    # Keywords tried in order & stops after first successful open
    for kw in IMPORTANT_KEYWORDS:
        print(f"Trying to open notification containing: {kw}")
        if open_notification_by_keyword(driver, kw):
            opened_pkg = driver.current_package
            print(f"Opened app package: {opened_pkg}")
            break

    if not opened_pkg:
        print("No important notification opened (none present)")

finally:
    driver.quit()

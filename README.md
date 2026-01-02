# android-notification-automation
Python-based Appium automation for Android notifications. Expands the notification shade, extracts and classifies notification text using UI and XML analysis, dismisses non-important notifications, and opens high-priority alerts via keyword-based logic. Designed for Android SystemUI.

## Features
- Opens and expands the Android notification shade
- Expands grouped notifications
- Extracts notification text across different Android UI variations
- Dismisses non-important notifications
- Opens high-priority notifications based on keywords

## Tech Stack
- Python
- Appium (UiAutomator2)
- Android SystemUI

## Requirements
- Python 3.9+
- Appium Server (v2.x)
- Android Emulator or physical Android device
- Android SDK

## Setup
1. Clone the repository
2. Install dependencies:
   ```bash
   pip install Appium-Python-Client
   ```
3. Start the Appium server:
   ```bash
   appium
   ```
4. Launch an Android emulator or connect a device

## Usage
Run the script:
```bash
python clear_notifications.py
```

Update the `IMPORTANT_KEYWORDS` list in the script to control which notifications are preserved and opened.

## Future Work: AI Enhancements

This project is designed to be extended with AI and ML to improve robustness and intelligence:

### Next Step:
- **Notification Classification**  
  Replace keyword matching with an NLP model to categorize notifications by intent, such as security, finance, delivery, authentication, etc.

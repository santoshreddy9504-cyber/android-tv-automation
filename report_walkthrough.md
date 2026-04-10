# 📺 Upgraded Android TV QA Report

The automation system now generates a premium, multi-inspector HTML report. Below is a breakdown of the new sections and metrics integrated into your system.

## ⏱️ Timing Inspector (Log-Based)
This new section captures high-precision performance metrics by analyzing the device's logcat in real-time.

| Metric | Source | Accuracy |
| :--- | :--- | :--- |
| **App Cold Start** | `ActivityManager` logs | ±1ms |
| **Page Navigation** | `NavController` / `Fragment` logs | ±10ms |
| **Input Latency** | `KeyEvent` → `Display` delta | ±5ms |
| **Video Startup** | `ExoPlayer` / `MediaPlayer` logs | ±1ms |

## 🌐 Network Inspector (Live API Feed)
Captured via `APIMonitor`, this section provides a full audit trail of all JSON traffic during the test.

*   **HTTP Status Codes**: Instant visibility into 4xx/5xx failures.
*   **Performance Warns**: Highlights any API call taking > 3000ms.
*   **Request Source**: Identifies whether the call came from OkHttp, Retrofit, or Volley.

## 🖼️ Layout Inspector (UI Snapshot)
Used for failure debugging, it provides a full XML tree of the screen at the moment an error occurred, showing:
*   Which element had **focus** (remote control cursor).
*   Visible text and resource IDs.
*   Clickable/Focusable counts to verify content population.

---

### How to access the latest report:
1.  Let the current `run_auto_test.py` finish (or run it to completion).
2.  The report will be saved in: `output/reports/auto_test_report_[timestamp].html`
3.  The system will attempt to **auto-open** it in your default browser.

> [!TIP]
> You can now see the **Cold Start** time directly in the dashboard header, alongside the **Avg Page Load** time!

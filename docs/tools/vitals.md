# Android Vitals

Tools for reading **Android vitals** — the crash, ANR, startup, and battery data behind the Play Console's Vitals page — through the [Play Developer Reporting API](https://developers.google.com/play/developer/reporting) (`playdeveloperreporting` v1beta1).

!!! info "Read-only by construction"
    The Reporting API defines no write methods: its entire surface is `get`, `query`, `search`, and `list`. Nothing in this section can modify Play Console data, so these tools are **not** gated by `--read-only` / `PLAY_STORE_MCP_READ_ONLY`.

## Requirements

Vitals sit behind **two independent gates**. Both are required, they are granted in different places, and neither implies the other.

| Gate | Where | What |
|---|---|---|
| App-level permission | Play Console → **Users and permissions** → App permissions | **View app quality information (read-only)** (`CAN_VIEW_APP_QUALITY`) for each app you want vitals for. The account-level release/review permissions used by the rest of this server do **not** include it. |
| API enablement | Google Cloud Console → **APIs & Services** → Enable APIs | **Google Play Developer Reporting API** (`playdeveloperreporting.googleapis.com`), in the project the service account key belongs to. This is a different API from the Google Play Android Developer API (`androidpublisher`) used by the publishing tools. |

The server requests the `https://www.googleapis.com/auth/playdeveloperreporting` OAuth scope alongside the existing `androidpublisher` scope. A scope only selects which APIs a token may address — all real authorization comes from the Play Console permissions above.

Vitals also only exist for apps that have been **published on Google Play**.

## Quota

The Reporting API's default quota is roughly **10 queries per second**. That is low enough that fan-out patterns break it, so these tools are shaped to avoid them:

- Breakdowns are a `dimensions` argument on a **single** query, not one query per dimension value.
- [`get_vitals_summary`](#get_vitals_summary) costs exactly **three** queries and takes no `dimensions`.
- `max_results` bounds pagination — keep it to the number of results actually worth reading.

## Reading the numbers

Rates are **fractions, not percentages**: `0.0109` means 1.09%. Google's bad-behavior thresholds are:

| Metric | Threshold |
|---|---|
| `userPerceivedCrashRate` | 1.09% |
| `userPerceivedAnrRate` | 0.47% |

Each timeline also reports `distinctUsers`, the denominator those rates are computed over.

## Empty results

An app with no vitals data returns an **empty but valid** payload with a `note` explaining the likely cause — it does not raise. Likely causes, in the order worth checking:

1. Too little traffic for Play to report on.
2. The window runs past the data's freshness — see [`get_metric_freshness`](#get_metric_freshness). Vitals lag real time by hours to days, so a window ending today normally has an empty tail.
3. The filter matched nothing.
4. The service account lacks `CAN_VIEW_APP_QUALITY` for the app.

---

## get_vitals_summary

An app's headline vitals — crash, ANR, and slow start — over one shared window. The tool for "how healthy is this app?" or "did the last release regress stability?".

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `package_name` | string | Yes | — | App package name |
| `days` | int | No | `28` | Trailing window in days, ending today (exclusive) |

Returns `crash_rate`, `anr_rate`, and `slow_start_rate` timelines plus the shared `start_date` / `end_date`, so the three can be read against each other without further calls.

Costs exactly **three** Reporting API queries — one per metric set, no breakdown. For a per-version or per-device split, call the individual tools with an explicit `dimensions` list.

```python
get_vitals_summary("com.example.myapp")

# A tighter window, e.g. since a release
get_vitals_summary("com.example.myapp", days=7)
```

---

## get_crash_rate

Daily crash-rate timeline.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `package_name` | string | Yes | — | App package name |
| `days` | int | No | `28` | Trailing window in days, ending today (exclusive) |
| `dimensions` | list[string] | No | `null` | Breakdown resolved inside the same single query |

Metrics returned: `crashRate` (any crash), `userPerceivedCrashRate` (a crash while the user was actively using the app — the metric the 1.09% threshold applies to), and `distinctUsers`.

```python
# App-wide daily timeline
get_crash_rate("com.example.myapp")

# Which version regressed? Still one query.
get_crash_rate("com.example.myapp", dimensions=["versionCode"])

# Which devices? Also one query.
get_crash_rate("com.example.myapp", days=14, dimensions=["deviceModel", "apiLevel"])
```

---

## get_anr_rate

Daily ANR (Application Not Responding) rate timeline.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `package_name` | string | Yes | — | App package name |
| `days` | int | No | `28` | Trailing window in days, ending today (exclusive) |
| `dimensions` | list[string] | No | `null` | Breakdown resolved inside the same single query |

Metrics returned: `anrRate`, `userPerceivedAnrRate` (the metric the 0.47% threshold applies to), and `distinctUsers`.

```python
get_anr_rate("com.example.myapp", dimensions=["versionCode"])
```

---

## get_slow_start_rate

Daily slow-app-start rate — the fraction of users who saw a start slower than the Android vitals threshold for its start type (5s cold, 2s warm, 1.5s hot).

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `package_name` | string | Yes | — | App package name |
| `days` | int | No | `28` | Trailing window in days, ending today (exclusive) |
| `dimensions` | list[string] | No | `null` | Breakdown resolved inside the same single query |

```python
# Split COLD/WARM/HOT inside the same single query — cold start is
# usually the one worth acting on.
get_slow_start_rate("com.example.myapp", dimensions=["startType"])
```

---

## get_excessive_wakeup_rate

Daily excessive-wakeup rate — the fraction of users whose device the app woke more than 10 times per hour. This is the Android vitals signal for alarm and JobScheduler abuse draining battery.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `package_name` | string | Yes | — | App package name |
| `days` | int | No | `28` | Trailing window in days, ending today (exclusive) |
| `dimensions` | list[string] | No | `null` | Breakdown resolved inside the same single query |

```python
get_excessive_wakeup_rate("com.example.myapp", dimensions=["versionCode"])
```

---

## search_error_issues

Crash and ANR **issues** — reports clustered by root cause. This is the "top crashes" view and the level to triage at.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `package_name` | string | Yes | — | App package name |
| `days` | int | No | `28` | Trailing window in days, ending today (exclusive) |
| `filter_expression` | string | No | `null` | AIP-160 filter over `apiLevel`, `versionCode`, `deviceModel`, `errorIssueType` (`CRASH`, `ANR`, `NON_FATAL`) |
| `order_by` | string | No | `errorReportCount desc` | `errorReportCount` or `distinctUsers`, each with ` asc` / ` desc` |
| `max_results` | int | No | `25` | Maximum issues to return |

Each issue carries its report and user counts. Pass an issue's ID to [`search_error_reports`](#search_error_reports) for the stack traces behind it.

```python
# What should we fix first?
search_error_issues("com.example.myapp", max_results=10)

# Only ANRs on the latest version
search_error_issues(
    "com.example.myapp",
    filter_expression="errorIssueType = ANR AND versionCode = 1200",
    order_by="distinctUsers desc",
)
```

---

## search_error_reports

Individual crash and ANR reports — one captured error each, with stack trace, app version, device model, and OS level.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `package_name` | string | Yes | — | App package name |
| `issue_id` | string | No | `null` | Issue from `search_error_issues`, as the bare ID or the full `apps/{package}/errorIssues/{id}` name |
| `days` | int | No | `28` | Trailing window in days, ending today (exclusive) |
| `filter_expression` | string | No | `null` | AIP-160 filter over `versionCode`, `deviceModel`, `errorIssueType`, `isUserPerceived` |
| `max_results` | int | No | `25` | Maximum reports to return |

Omit `issue_id` to sample recent reports across the whole app. When both `issue_id` and `filter_expression` are given, they are combined.

```python
# Stack traces behind one issue
search_error_reports("com.example.myapp", issue_id="abc123", max_results=5)
```

---

## list_anomalies

Anomalies Play itself detected — a metric moving well outside the app's expected range. This is the signal behind Play Console vitals alerts, and the cheapest way to ask "did anything get worse?" before spending queries on full timelines.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `package_name` | string | Yes | — | App package name |
| `days` | int | No | `null` | Only anomalies still active within this trailing window. Omit for every anomaly Play currently holds. |
| `max_results` | int | No | `25` | Maximum anomalies to return |

An empty list is good news, and says so in a `note`.

```python
# Anything flagged in the last week?
list_anomalies("com.example.myapp", days=7)
```

---

## get_metric_freshness

How current a metric set's data is — the latest available end time per aggregation period (`HOURLY`, `DAILY`, `FULL_RANGE`).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `package_name` | string | Yes | App package name |
| `metric_set` | string | Yes | Metric set to inspect (see below) |

Valid metric sets: `crashRateMetricSet`, `anrRateMetricSet`, `excessiveWakeupRateMetricSet`, `stuckBackgroundWakelockRateMetricSet`, `slowStartRateMetricSet`, `slowRenderingRateMetricSet`, `lmkRateMetricSet`, `errorCountMetricSet`.

Call this when a query comes back empty, when a recent regression appears to have "disappeared", or before comparing two windows.

```python
get_metric_freshness("com.example.myapp", "crashRateMetricSet")
```

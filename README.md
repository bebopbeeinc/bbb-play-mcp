# Play Store MCP Server

[![CI](https://github.com/lusky3/play-store-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/lusky3/play-store-mcp/actions/workflows/ci.yml)
[![codecov](https://codecov.io/github/lusky3/play-store-mcp/graph/badge.svg?token=iDdVHHp5Jw)](https://codecov.io/github/lusky3/play-store-mcp)
[![Security Rating](https://sonarcloud.io/api/project_badges/measure?project=lusky3_play-store-mcp&metric=security_rating)](https://sonarcloud.io/summary/new_code?id=lusky3_play-store-mcp)
[![Reliability Rating](https://sonarcloud.io/api/project_badges/measure?project=lusky3_play-store-mcp&metric=reliability_rating)](https://sonarcloud.io/summary/new_code?id=lusky3_play-store-mcp)
[![Maintainability Rating](https://sonarcloud.io/api/project_badges/measure?project=lusky3_play-store-mcp&metric=sqale_rating)](https://sonarcloud.io/summary/new_code?id=lusky3_play-store-mcp)
[![Vulnerabilities](https://sonarcloud.io/api/project_badges/measure?project=lusky3_play-store-mcp&metric=vulnerabilities)](https://sonarcloud.io/summary/new_code?id=lusky3_play-store-mcp)

[![PyPI version](https://badge.fury.io/py/play-store-mcp.svg)](https://badge.fury.io/py/play-store-mcp)
[![Docker](https://img.shields.io/badge/ghcr.io-play--store--mcp-blue?logo=docker)](https://github.com/lusky3/play-store-mcp/pkgs/container/play-store-mcp)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Lines of Code](https://sonarcloud.io/api/project_badges/measure?project=lusky3_play-store-mcp&metric=ncloc)](https://sonarcloud.io/summary/new_code?id=lusky3_play-store-mcp)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

An MCP (Model Context Protocol) server that connects to the Google Play Developer API. Deploy apps, manage releases, respond to reviews, and monitor app health — all through your AI assistant.

📖 **[Full Documentation](https://lusky3.github.io/play-store-mcp)**

> **About this fork.** This is a fork of [lusky3/play-store-mcp](https://github.com/lusky3/play-store-mcp) that adds **Android vitals** — read-only crash, ANR, startup, battery, and anomaly data from the [Google Play Developer Reporting API](https://developers.google.com/play/developer/reporting), which upstream does not cover. Everything else tracks upstream, and the vitals work is intended to be contributed back there.

## ✨ Features

- 🚀 **App Deployment** — Deploy APK/AAB files to any track (internal, alpha, beta, production)
- ⚡ **Batch Operations** — Deploy to multiple tracks simultaneously
- 🌐 **Multi-Language Support** — Deploy with release notes in multiple languages
- ✅ **Input Validation** — Validate package names, tracks, and text before API calls
- 🔄 **Automatic Retries** — Built-in retry logic with exponential backoff for transient failures
- 📝 **Store Listings** — Update app titles, descriptions, and videos for any language
- 📈 **Release Management** — Promote releases between tracks, manage staged rollouts
- 👥 **Tester Management** — Add and manage testers for testing tracks
- ⭐ **Review Management** — Fetch and reply to user reviews
- 📊 **Android Vitals** — Read crash, ANR, startup, and battery metrics, top crash issues, and Play-detected anomalies (read-only)
- 💳 **Subscription Management** — List subscriptions and check purchase status
- 🛒 **One-Time Products** — List and manage the one-time product catalog
- 📦 **Expansion Files** — Manage APK expansion files for large apps
- 🧾 **Orders** — Retrieve detailed transaction information
- 🐳 **Docker Support** — Run as a container with health checks
- 🔑 **Per-Request Credentials** — Bring-your-own-credentials for multi-tenant deployments
- 🔒 **Secure** — Google Cloud service account authentication

## 🚀 Quick Start

### Prerequisites

1. **Google Cloud Project** with the Google Play Developer API enabled
2. **Service Account** with access to your Play Console
3. **Python 3.11+**, `uvx`, or **Docker** installed

### Installation

#### Using uvx (Recommended)

```bash
# Run directly without installation
uvx play-store-mcp
```

#### Using pip

```bash
pip install play-store-mcp
play-store-mcp
```

#### Using Docker

```bash
docker run -e GOOGLE_APPLICATION_CREDENTIALS=/creds/key.json \
  -v /path/to/service-account.json:/creds/key.json:ro \
  ghcr.io/lusky3/play-store-mcp:latest
```

#### From source

```bash
git clone https://github.com/lusky3/play-store-mcp.git
cd play-store-mcp
pip install -e .
play-store-mcp
```

### Configuration

Set the path to your service account key:

```bash
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
```

### Running with HTTP Transport

For remote access or public deployments, run the server with streamable-http transport:

```bash
play-store-mcp --transport streamable-http --host 0.0.0.0 --port 8000
```

The server exposes a `/health` endpoint for monitoring.

#### Per-Request Credentials (Recommended for Public Instances)

For public deployments where users bring their own credentials, configure your MCP client to pass credentials in headers:

```json
{
  "mcpServers": {
    "play-store": {
      "url": "https://your-server.com/mcp",
      "transport": "http",
      "headers": {
        "X-Google-Credentials-Base64": "YOUR_BASE64_ENCODED_CREDENTIALS"
      }
    }
  }
}
```

To get your base64-encoded credentials:

```bash
base64 -w 0 < service-account.json
```

Per-request credentials are isolated — each request uses only the credentials provided in its headers. No credentials are stored server-side or shared between requests.

#### Server-Side Credentials (For Private/Trusted Deployments)

For private deployments, set credentials via environment variable at server startup:

```bash
export GOOGLE_PLAY_STORE_CREDENTIALS='{"type":"service_account",...}'
# or
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json

play-store-mcp --transport streamable-http --host 0.0.0.0 --port 8000
```

### Read-Only Mode

To point the server at a live Play Console without any risk of mutating it, run
in read-only mode. All write tools (deploy, promote, halt, rollout, reply to
reviews, listing/tester updates) return an error instead of calling the API;
read tools are unaffected.

```bash
play-store-mcp --read-only
# or
export PLAY_STORE_MCP_READ_ONLY=1
```

### Code Mode (Experimental)

Opt in to the experimental code-mode transform to serve the tools as three
meta-tools (`search`/`get_schema`/`execute`) instead of the full tool list,
cutting per-request tool-list token overhead. It is off by default. Install the
sandbox extra and set the environment variable (`CODE_MODE` is env-only — there
is no CLI flag):

```bash
pip install "play-store-mcp[code-mode]"
export CODE_MODE=1
```

Under code mode one `execute` call can invoke up to 50 tool calls (including mutations) behind a single approval. Read-only enforcement still applies inside the sandbox, so pair it with `--read-only` / `PLAY_STORE_MCP_READ_ONLY=1` unless you need writes.

## 🔧 MCP Client Configuration

### Claude Desktop

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "play-store": {
      "command": "uvx",
      "args": ["play-store-mcp"],
      "env": {
        "GOOGLE_APPLICATION_CREDENTIALS": "/path/to/service-account.json"
      }
    }
  }
}
```

### Kiro

Add to `.kiro/settings/mcp.json`:

```json
{
  "mcpServers": {
    "play-store": {
      "command": "uvx",
      "args": ["play-store-mcp"],
      "env": {
        "GOOGLE_APPLICATION_CREDENTIALS": "/path/to/service-account.json"
      }
    }
  }
}
```

### Gemini CLI / Other MCP Clients

```json
{
  "mcpServers": {
    "play-store": {
      "command": "uvx",
      "args": ["play-store-mcp"],
      "env": {
        "GOOGLE_APPLICATION_CREDENTIALS": "/path/to/service-account.json"
      }
    }
  }
}
```

## 🛠️ Available Tools

### Publishing Tools

| Tool | Description |
| --- | --- |
| `deploy_app` | Deploy an APK/AAB to a track with optional staged rollout and single-language release notes |
| `deploy_app_multilang` | Deploy an APK/AAB with multi-language release notes |
| `promote_release` | Promote a release from one track to another |
| `get_releases` | Get release status for all tracks |
| `halt_release` | Halt a staged rollout |
| `update_rollout` | Update rollout percentage for a staged release |
| `get_app_details` | Get app metadata (title, description, etc.) |

### Store Listings Tools

| Tool | Description |
| --- | --- |
| `get_listing` | Get store listing for a specific language |
| `update_listing` | Update store listing (title, descriptions, video) |
| `list_all_listings` | List all store listings for all languages |

### Review Tools

| Tool | Description |
| --- | --- |
| `get_reviews` | Fetch recent reviews with optional filters |
| `reply_to_review` | Reply to a user review |

### Android Vitals Tools

Backed by the [Play Developer Reporting API](https://developers.google.com/play/developer/reporting) (`playdeveloperreporting` v1beta1) — the same data as the Play Console's **Android vitals** page. **Every tool here is read-only**: the Reporting API defines no write methods, so nothing in this section can change anything in Play Console, and `--read-only` mode does not gate them.

| Tool | Description |
| --- | --- |
| `get_vitals_summary` | Crash, ANR, and slow-start timelines over one shared window — the "how healthy is this app?" tool |
| `get_crash_rate` | Daily crash-rate timeline (`crashRate`, `userPerceivedCrashRate`, `distinctUsers`) |
| `get_anr_rate` | Daily ANR-rate timeline (`anrRate`, `userPerceivedAnrRate`, `distinctUsers`) |
| `get_slow_start_rate` | Daily slow-app-start rate; break down by `startType` for cold/warm/hot |
| `get_excessive_wakeup_rate` | Daily excessive-wakeup rate (battery drain from alarms/JobScheduler) |
| `search_error_issues` | Crash/ANR issues grouped by root cause — the "top crashes" view |
| `search_error_reports` | Individual crash/ANR reports (stack traces) behind an issue |
| `list_anomalies` | Anomalies Play itself detected — the cheapest "did anything get worse?" check |
| `get_metric_freshness` | How current a metric set's data is, per aggregation period |

Rates are fractions, not percentages: `0.0109` is 1.09%. Google's bad-behavior thresholds are **1.09%** for `userPerceivedCrashRate` and **0.47%** for `userPerceivedAnrRate`.

`get_metric_freshness` accepts any of: `crashRateMetricSet`, `anrRateMetricSet`, `excessiveWakeupRateMetricSet`, `stuckBackgroundWakelockRateMetricSet`, `slowStartRateMetricSet`, `slowRenderingRateMetricSet`, `lmkRateMetricSet`, `errorCountMetricSet`.

#### Requirements — two separate gates, both needed

Vitals fail with a permission error unless **both** of these are done. They are granted in different places and neither implies the other:

1. **App-level Play Console permission: "View app quality information (read-only)"** (`CAN_VIEW_APP_QUALITY`) — granted per app under **Play Console → Users and permissions → App permissions**. The account-level release/review permissions used by the rest of this server do **not** include it.
2. **The Google Play Developer Reporting API enabled** in the Cloud project the service account key belongs to — **Google Cloud Console → APIs & Services → Enable APIs**, `playdeveloperreporting.googleapis.com`. This is a different API from the Google Play Android Developer API (`androidpublisher`) that the publishing tools use, and enabling one does not enable the other.

The server requests the `https://www.googleapis.com/auth/playdeveloperreporting` OAuth scope alongside the existing `androidpublisher` one. A scope only selects which APIs a token may address — all actual authorization still comes from the Play Console permissions above, and the Reporting API has no write methods to grant.

#### Quota

The Reporting API's default quota is roughly **10 queries per second**, which is low enough that fan-out patterns break it. These tools are shaped around that:

- A breakdown is a `dimensions` argument on a **single** query (e.g. `get_crash_rate(pkg, dimensions=["versionCode"])`), never one query per dimension value.
- `get_vitals_summary` costs exactly **three** queries — one per metric set, with no breakdown. Ask the per-metric tools for a breakdown when you actually need one.
- `max_results` bounds pagination, so keep it to what is worth reading.

#### When vitals come back empty

An empty result is a valid answer, not an error — the tools return an empty payload with a `note` listing the likely causes rather than raising. Check, in order: the app has enough traffic for Play to report on; the window is inside the data's freshness (`get_metric_freshness`); any filter matches something; and the service account has `CAN_VIEW_APP_QUALITY` for that app. Vitals also only exist for apps that have been published on Google Play.

### Subscription Tools

| Tool | Description |
| --- | --- |
| `list_subscriptions` | List subscription products for an app |
| `get_subscription_status` | Check subscription purchase status |
| `list_voided_purchases` | List voided purchases |

### One-Time Product Tools

The retired `v3.inappproducts` resource (Google returns
`403 "Please migrate to the new publishing API"`) has been replaced by
`monetization.oneTimeProducts`. The `*_in_app_product(s)` tools were removed;
use these instead. Note that `sku` is now `product_id`, and pricing lives in
`purchaseOptions` rather than a flat `defaultPrice`.

| Tool | Description |
| --- | --- |
| `list_one_time_products` | List all one-time products for an app |
| `get_one_time_product` | Get details of a specific one-time product |
| `batch_get_one_time_products` | Get details for multiple one-time products at once |
| `patch_one_time_product` | Update a product, or create it with `allow_missing=True` |
| `delete_one_time_product` | Delete a one-time product |
| `batch_update_one_time_products` | Update multiple one-time products at once |
| `batch_delete_one_time_products` | Delete multiple one-time products at once |

### Testers Management Tools

| Tool | Description |
| --- | --- |
| `get_testers` | Get testers for a specific testing track |
| `update_testers` | Update testers for a testing track |

### Orders Tools

| Tool | Description |
| --- | --- |
| `get_order` | Get detailed order/transaction information |

### Expansion Files Tools

| Tool | Description |
| --- | --- |
| `get_expansion_file` | Get APK expansion file information |

### Validation Tools

| Tool | Description |
| --- | --- |
| `validate_package_name` | Validate package name format |
| `validate_track` | Validate track name |
| `validate_listing_text` | Validate store listing text lengths |

### Batch Operations Tools

| Tool | Description |
| --- | --- |
| `batch_deploy` | Deploy to multiple tracks simultaneously |

## 📋 Google Cloud Setup

### 1. Create a Service Account

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing one
3. Enable the **Google Play Android Developer API** (`androidpublisher`)
4. Enable the **Google Play Developer Reporting API** (`playdeveloperreporting`) — required for the Android vitals tools only; skip it if you do not need them
5. Go to **IAM & Admin** > **Service Accounts**
6. Create a new service account
7. Download the JSON key file

### 2. Grant Play Console Access

1. Go to [Google Play Console](https://play.google.com/console/)
2. Navigate to **Users and permissions**
3. Click **Invite new users**
4. Enter the service account email (from the JSON file)
5. Grant the following permissions:
   - **Release apps to testing tracks** (for internal/alpha/beta)
   - **Release apps to production** (for production releases)
   - **Reply to reviews** (for review management)
   - **View app information and download bulk reports** (for app details and orders)
   - **View app quality information (read-only)** — `CAN_VIEW_APP_QUALITY`, granted per app under **App permissions**; required for the Android vitals tools

## 🔒 Environment Variables

| Variable | Description | Required |
| --- | --- | --- |
| `GOOGLE_APPLICATION_CREDENTIALS` | Path to service account JSON key | Yes (or use per-request credentials) |
| `GOOGLE_PLAY_STORE_CREDENTIALS` | Inline JSON credentials string | Alternative to file path |
| `PLAY_STORE_MCP_LOG_LEVEL` | Log level (DEBUG, INFO, WARNING, ERROR) | No (default: INFO) |
| `PLAY_STORE_MCP_DISABLE_DNS_REBINDING` | Disable DNS rebinding protection (for cloud/reverse-proxy deployments) | No |
| `PLAY_STORE_MCP_ADMIN_TOKEN` | Require `Authorization: Bearer <token>` on the `/credentials` endpoint (for deployments behind a reverse proxy) | No |
| `PLAY_STORE_MCP_READ_ONLY` | Disable all write operations (deploy, promote, rollout, reply, listing/tester updates) | No (default: off) |
| `PLAY_STORE_MCP_DOWNLOAD_DIR` | Directory that APK/AAB downloads are confined to (path-traversal / arbitrary-write protection). Downloads are always confined; defaults to the working directory when unset | No for `stdio` (defaults to cwd); **required** for network transports |
| `CODE_MODE` | Enable the experimental code-mode transform (opt-in; requires the `play-store-mcp[code-mode]` extra) | No (default: off) |

## 🧪 Development

### Setup

```bash
git clone https://github.com/lusky3/play-store-mcp.git
cd play-store-mcp
uv sync --dev
```

### Running Tests

```bash
uv run pytest -v --cov=src/play_store_mcp
```

### Linting

```bash
ruff check src/ tests/
ruff format src/ tests/
```

### Type Checking

```bash
mypy src/
```

## 🐛 Troubleshooting

### Error: "Service account key not found"

Ensure `GOOGLE_APPLICATION_CREDENTIALS` points to a valid JSON file:

```bash
ls -la $GOOGLE_APPLICATION_CREDENTIALS
```

### Error: "The caller does not have permission"

Verify the service account has been granted access in Play Console with the required permissions.

### Error: "Package name not found"

Ensure the app exists in Play Console and the service account has access to it.

### Vitals: "access to ... was denied" or empty results

Android vitals sit behind two independent gates — check both:

1. The service account has **View app quality information (read-only)** (`CAN_VIEW_APP_QUALITY`) **for that specific app** in Play Console → Users and permissions → App permissions. Account-level release permissions do not include it.
2. The **Google Play Developer Reporting API** is enabled in the Cloud project the key belongs to. Enabling the Google Play Android Developer API does not enable it.

If the call succeeds but returns nothing, the result carries a `note` with the likely cause. Run `get_metric_freshness` first — vitals lag real time by hours to days, so a window running up to today often has an empty tail.

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

## 🙏 Acknowledgments

- Forked from [lusky3/play-store-mcp](https://github.com/lusky3/play-store-mcp); this fork adds the Android vitals tools, with the intent to upstream them
- Inspired by [antoniolg/play-store-mcp](https://github.com/antoniolg/play-store-mcp) (Kotlin)
- Built with the [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- Uses the [Google Play Developer API](https://developers.google.com/android-publisher) and the [Google Play Developer Reporting API](https://developers.google.com/play/developer/reporting)

## 🤖 AI Usage Disclaimer

Portions of this codebase were generated with the assistance of Large Language Models (LLMs). All AI-generated code has been reviewed and tested to ensure quality and correctness.

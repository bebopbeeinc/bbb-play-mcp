# Testing Documentation

## Overview

All tests in this project use **mocked Google Play API responses** - no live API calls are made during testing. This ensures:

- ✅ Tests run without Google Cloud credentials
- ✅ No actual changes are made to Play Console
- ✅ Tests are fast and deterministic
- ✅ Safe to run in CI/CD pipelines

## Test Structure

### Test Files

- `tests/test_client.py` - Tests for PlayStoreClient methods (API interactions)
- `tests/test_server.py` - Tests for MCP server tools
- `tests/test_models.py` - Tests for Pydantic data models
- `tests/test_reporting_client.py` - Tests for the Play Developer Reporting API client (Android vitals)
- `tests/test_vitals.py` - Tests for the Android vitals MCP tools
- `tests/conftest.py` - Pytest fixtures and mocked dependencies

### Mocking Strategy

All Google API interactions are mocked using `unittest.mock`:

```python
@pytest.fixture
def _mock_service() -> Generator[MagicMock, None, None]:
    """Mock the Google API service."""
    with patch("play_store_mcp.client.build") as mock_build:
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        yield mock_service
```

This means:

- No real HTTP requests are made
- No authentication is required
- Tests return predefined responses
- All operations are safe and isolated

## Running Tests

### Unit Tests (Mocked - Safe)

These tests use mocked API responses and never make real API calls.

```bash
# Using uv (Recommended)
uv run pytest tests/ -v

# Using the test script
./tests/run_tests.sh

# With coverage report
uv run pytest tests/ -v --cov=src/play_store_mcp --cov-report=term-missing

# Run only unit tests (exclude integration)
uv run pytest tests/ -v --ignore=tests/test_integration.py
```

### Integration Tests (Real API - Read-Only)

These tests use real Google Play API credentials but only perform READ operations.

Prerequisites:

1. Valid Google Cloud service account credentials
2. Service account with Play Console access
3. At least one app in your Play Console account

Setup:

```bash
# 1. Ensure .env.local has credentials
cat .env.local
# Should contain: export GOOGLE_APPLICATION_CREDENTIALS="..."

# 2. Set test package name (optional but recommended)
export TEST_PACKAGE_NAME=com.your.app.package

# 3. Run integration tests
./tests/run_integration_tests.sh
```

What Integration Tests Do:

- ✅ Verify real API connectivity
- ✅ Test authentication works
- ✅ Read app releases and details
- ✅ Fetch reviews and listings
- ✅ List subscriptions and products
- ✅ Test validation functions

What Integration Tests DON'T Do:

- ❌ Deploy apps
- ❌ Modify releases
- ❌ Update store listings
- ❌ Reply to reviews
- ❌ Make ANY changes to Play Console

All integration tests are read-only. They will never modify your Play Console data.

## Test Coverage

### Client Tests (`test_client.py`)

#### Initialization and Setup

- ✅ Missing credentials error handling
- ✅ Environment variable configuration

#### Publishing Operations

- ✅ Get releases from all tracks
- ✅ Deploy APK files
- ✅ Deploy AAB files
- ✅ Deploy with staged rollout
- ✅ Deploy with multi-language release notes
- ✅ Promote releases between tracks
- ✅ Version not found error handling

#### Reviews

- ✅ Fetch reviews with filters
- ✅ Reply to reviews

#### Subscriptions

- ✅ List subscription products
- ✅ Get subscription purchase status

#### In-App Products

- ✅ List in-app products
- ✅ Get specific product details

#### Store Listings

- ✅ Get listing for specific language
- ✅ Update listing (title, descriptions, video)
- ✅ List all language listings

#### Testers Management

- ✅ Get testers for a track
- ✅ Update testers list

#### Orders

- ✅ Get order details

#### Expansion Files

- ✅ Get expansion file information

#### Validation

- ✅ Validate package name format
- ✅ Validate track names
- ✅ Validate listing text lengths
- ✅ Catch invalid inputs

#### Batch Operations

- ✅ Deploy to multiple tracks simultaneously
- ✅ Track individual results

### Android Vitals Tests (`test_reporting_client.py`, `test_vitals.py`)

Android vitals go through a **second** Google API — `playdeveloperreporting`
v1beta1 — with its own OAuth scope and its own discovery build, so it gets its
own mocked service (`client._reporting_service`) rather than the
androidpublisher one used everywhere else.

#### Client (`test_reporting_client.py`)

- ✅ Both scopes requested; reporting service built separately, cached, and
  never substituted for the publishing service
- ✅ Resource names — `apps/{package}/{metricSet}` verified for **all eight**
  metric sets, each through its own discovery path
- ✅ Request construction: timeline specs, DAILY vs HOURLY bounds, AIP-160
  filters, flattened `interval.*` params for the error searches
- ✅ Argument validation that costs no API call (unknown metric set, bad date
  format, hour on a DAILY timeline, empty metrics, `user_cohort` on
  `errorCountMetricSet`)
- ✅ Pagination up to `max_results`, page-size capping per method, truncation
  reported via `nextPageToken`, and the empty-page guard against an endless loop
- ✅ 401/403 name the missing `CAN_VIEW_APP_QUALITY` permission; 404 explains
  the package name; 429 explains the ~10 QPS quota
- ✅ Empty results are annotated with likely causes instead of raising
- ✅ Read-only property: no reporting call ever dispatches a mutating discovery
  method

#### Tools (`test_vitals.py`)

- ✅ Each tool's returned shape, window, and metric set
- ✅ Every windowed tool rejects an out-of-range `days` without calling the API
- ✅ Empty data and permission failures as an MCP caller sees them
- ✅ Vitals are not gated by `--read-only` (the Reporting API has no writes)
- ✅ **Quota safety**: `get_vitals_summary` makes exactly three queries, pinned
  both at the client boundary and at the transport, with no per-dimension
  fan-out; a `dimensions` breakdown stays a single round trip

### Server Tests (`test_server.py`)

- ✅ Server module imports correctly
- ✅ All 27 MCP tools are defined
- ✅ Tool functions are accessible

### Model Tests (`test_models.py`)

#### Enums

- ✅ Track enum values

#### Data Models

- ✅ Release model (minimal and full)
- ✅ DeploymentResult (success and failure)
- ✅ Review model (with and without replies)
- ✅ AppDetails model
- ✅ SubscriptionProduct model
- ✅ OneTimeProduct model
- ✅ Listing model
- ✅ TesterInfo model
- ✅ Order model
- ✅ ExpansionFile model

## What Tests Verify

### 1. API Client Behavior

Tests verify that the client correctly:

- Constructs API requests
- Handles API responses
- Processes data into models
- Handles errors gracefully

### 2. Data Validation

Tests verify that:

- Invalid package names are caught
- Invalid track names are rejected
- Text length limits are enforced
- Input validation prevents API errors

### 3. Business Logic

Tests verify that:

- Batch operations work correctly
- Multi-language support functions properly
- Rollout percentages are handled correctly
- Edit sessions are managed properly

### 4. Error Handling

Tests verify that:

- Missing files are detected
- API errors are caught and reported
- Version not found scenarios are handled
- Network errors trigger retries (via decorator)

## Retry Logic Testing

The `@retry_with_backoff` decorator retries transient errors (HTTP 429/500/503)
with exponential backoff. It is applied to `_get_service` and to
`PlayStoreClient._execute`, and **every** Play API call is routed through
`_execute`, so all real API operations (deploy, upload, list, purchases,
subscriptions, etc.) inherit the retry behavior.

It **is** directly unit-tested:

- The decorator itself is tested against dummy functions for the 429/500/503
  retry paths and the exhaustion path (`tests/test_client_extended.py`).
- Backoff sleeps are neutralized in tests by the autouse `_no_backoff_sleep`
  fixture in `tests/conftest.py`, which patches `time.sleep`, so retry paths
  run instantly and deterministically.
- Method-level tests assert that operations retry transient errors and then
  succeed or fail as expected.

## CI/CD Integration

Tests run automatically in GitHub Actions on:

- Every push to main
- Every pull request
- Multiple Python versions (3.11, 3.12, 3.13)

See `.github/workflows/ci.yml` for the full CI configuration.

## Manual Testing

For manual testing with real API calls:

1. Set up Google Cloud credentials
2. Create a test app in Play Console
3. Use the MCP server with a real service account
4. Test operations on internal track only
5. Never test on production track

**Warning**: Manual testing makes real changes to your Play Console. Always use a test app and internal track.

## Test Limitations

### What Tests DON'T Cover

1. **Real API Integration**
   - Tests use mocks, not real Google Play API
   - API changes won't be caught until runtime
   - Network issues aren't tested

2. **Authentication Flow**
   - Service account authentication is mocked
   - Token refresh isn't tested
   - Permission errors aren't fully tested

3. **Rate Limiting**
   - Retry logic exists but isn't unit tested
   - Rate limit behavior is assumed, not verified

4. **Large File Uploads**
   - File upload logic is mocked
   - Large file handling isn't tested
   - Upload progress isn't verified

5. **Concurrent Operations**
   - No tests for concurrent API calls
   - Thread safety isn't verified
   - Race conditions aren't tested

### Why These Limitations Exist

- **Speed**: Real API tests would be slow
- **Cost**: Real API calls may have costs
- **Safety**: Don't want to modify real apps
- **Reliability**: External APIs can be flaky
- **Isolation**: Unit tests should be isolated

## Recommendations

### For Development

- Run tests frequently during development
- Add tests for new features
- Mock external dependencies
- Keep tests fast and focused

### For Production

- Monitor API errors in production
- Set up alerting for failures
- Test manually on staging apps
- Review logs regularly

### For Contributors

- Write tests for new features
- Maintain test coverage above 80%
- Use existing fixtures
- Follow the mocking patterns

## Conclusion

The test suite provides **comprehensive coverage of business logic** while using mocks to avoid live API calls. This approach:

- ✅ Ensures code correctness
- ✅ Enables safe refactoring
- ✅ Catches regressions early
- ✅ Runs quickly in CI/CD
- ✅ Doesn't require credentials

However, **manual integration testing** is still recommended before major releases to verify real API behavior.

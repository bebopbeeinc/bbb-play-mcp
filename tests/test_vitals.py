"""Tests for the Android Vitals tools (Play Developer Reporting API)."""

from __future__ import annotations

import inspect
from datetime import UTC, date, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest

from play_store_mcp.client import (
    REPORTING_METRIC_SETS,
    PlayStoreClient,
    PlayStoreClientError,
)
from play_store_mcp.server import (
    DEFAULT_VITALS_DAYS,
    MAX_VITALS_DAYS,
    VITALS_AGGREGATION_PERIOD,
    get_anr_rate,
    get_crash_rate,
    get_excessive_wakeup_rate,
    get_metric_freshness,
    get_slow_start_rate,
    get_vitals_summary,
    list_anomalies,
    search_error_issues,
    search_error_reports,
)

PACKAGE = "com.example.app"


@pytest.fixture
def mock_client() -> MagicMock:
    """Create a mock PlayStoreClient.

    Deliberately unspecced: the reporting methods these tools call live in
    client.py, so speccing here would only re-test the client's surface.
    ``test_tool_calls_match_client_signatures`` covers that binding instead.
    """
    return MagicMock()


@pytest.fixture(autouse=True)
def _patch_mcp_context(mock_client: MagicMock, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Route get_client_from_context to the mock client for tool tests."""
    from play_store_mcp import server

    monkeypatch.setattr(server, "get_http_headers", dict)
    monkeypatch.setitem(server._shared_state, "client", mock_client)
    yield


def assert_trailing_window(result: dict[str, Any], days: int) -> None:
    """Assert the result covers a trailing window of `days` ending today (UTC)."""
    start = date.fromisoformat(result["start_date"])
    end = date.fromisoformat(result["end_date"])
    assert (end - start).days == days
    assert end <= datetime.now(UTC).date()
    assert result["days"] == days


# =========================================================================
# Metric set tools
# =========================================================================


class TestMetricSetTools:
    """Test the per-metric-set vitals tools."""

    @pytest.mark.parametrize(
        ("tool", "metric_set", "metrics"),
        [
            (
                get_crash_rate,
                "crashRateMetricSet",
                ["crashRate", "userPerceivedCrashRate", "distinctUsers"],
            ),
            (
                get_anr_rate,
                "anrRateMetricSet",
                ["anrRate", "userPerceivedAnrRate", "distinctUsers"],
            ),
            (
                get_excessive_wakeup_rate,
                "excessiveWakeupRateMetricSet",
                ["excessiveWakeupRate", "distinctUsers"],
            ),
            (
                get_slow_start_rate,
                "slowStartRateMetricSet",
                ["slowStartRate", "distinctUsers"],
            ),
        ],
    )
    def test_queries_expected_metric_set(
        self,
        mock_client: MagicMock,
        tool: Any,
        metric_set: str,
        metrics: list[str],
    ) -> None:
        """Each tool issues one query for its own metric set over a 28-day window."""
        mock_client.query_metric_set.return_value = {"rows": []}

        result = tool(PACKAGE)

        mock_client.query_metric_set.assert_called_once()
        kwargs = mock_client.query_metric_set.call_args.kwargs
        assert kwargs["package_name"] == PACKAGE
        assert kwargs["metric_set"] == metric_set
        assert kwargs["metrics"] == metrics
        assert kwargs["dimensions"] is None
        assert kwargs["aggregation_period"] == VITALS_AGGREGATION_PERIOD
        assert result["metric_set"] == metric_set
        assert result["data"] == {"rows": []}
        assert_trailing_window(result, DEFAULT_VITALS_DAYS)

    def test_custom_window_is_passed_through(self, mock_client: MagicMock) -> None:
        """A custom days value drives both the query dates and the reported window."""
        mock_client.query_metric_set.return_value = {"rows": []}

        result = get_crash_rate(PACKAGE, days=7)

        kwargs = mock_client.query_metric_set.call_args.kwargs
        assert kwargs["start_date"] == result["start_date"]
        assert kwargs["end_date"] == result["end_date"]
        assert_trailing_window(result, 7)

    def test_dimensions_are_resolved_in_one_query(self, mock_client: MagicMock) -> None:
        """Dimensions ride along inside the single query rather than fanning out."""
        mock_client.query_metric_set.return_value = {"rows": []}

        result = get_slow_start_rate(PACKAGE, dimensions=["startType"])

        mock_client.query_metric_set.assert_called_once()
        assert mock_client.query_metric_set.call_args.kwargs["dimensions"] == ["startType"]
        assert result["dimensions"] == ["startType"]

    @pytest.mark.parametrize("days", [0, -1, MAX_VITALS_DAYS + 1])
    def test_invalid_window_is_rejected(self, mock_client: MagicMock, days: int) -> None:
        """An out-of-range window returns an error without calling the API."""
        result = get_crash_rate(PACKAGE, days=days)

        assert "error" in result
        assert "days must be between" in result["error"]
        mock_client.query_metric_set.assert_not_called()

    def test_boundary_windows_are_accepted(self, mock_client: MagicMock) -> None:
        """The 1-day and max-day windows are valid."""
        mock_client.query_metric_set.return_value = {"rows": []}

        assert "error" not in get_crash_rate(PACKAGE, days=1)
        assert "error" not in get_crash_rate(PACKAGE, days=MAX_VITALS_DAYS)


# =========================================================================
# Vitals summary
# =========================================================================


class TestVitalsSummary:
    """Test the get_vitals_summary tool."""

    def test_queries_three_metric_sets_once_each(self, mock_client: MagicMock) -> None:
        """The summary costs exactly three queries — no per-dimension fan-out."""
        mock_client.query_metric_set.side_effect = [
            {"rows": ["crash"]},
            {"rows": ["anr"]},
            {"rows": ["slow_start"]},
        ]

        result = get_vitals_summary(PACKAGE)

        assert mock_client.query_metric_set.call_count == 3
        queried = [
            call.kwargs["metric_set"] for call in mock_client.query_metric_set.call_args_list
        ]
        assert queried == ["crashRateMetricSet", "anrRateMetricSet", "slowStartRateMetricSet"]
        assert all(
            call.kwargs["aggregation_period"] == VITALS_AGGREGATION_PERIOD
            for call in mock_client.query_metric_set.call_args_list
        )
        assert not any(
            "dimensions" in call.kwargs for call in mock_client.query_metric_set.call_args_list
        )
        assert result["crash_rate"] == {"rows": ["crash"]}
        assert result["anr_rate"] == {"rows": ["anr"]}
        assert result["slow_start_rate"] == {"rows": ["slow_start"]}
        assert result["metric_sets"] == queried

    def test_all_three_queries_share_one_window(self, mock_client: MagicMock) -> None:
        """The three timelines are comparable because they cover the same dates."""
        mock_client.query_metric_set.return_value = {"rows": []}

        result = get_vitals_summary(PACKAGE, days=14)

        windows = {
            (call.kwargs["start_date"], call.kwargs["end_date"])
            for call in mock_client.query_metric_set.call_args_list
        }
        assert windows == {(result["start_date"], result["end_date"])}
        assert_trailing_window(result, 14)

    def test_invalid_window_is_rejected(self, mock_client: MagicMock) -> None:
        """An out-of-range window returns an error without calling the API."""
        result = get_vitals_summary(PACKAGE, days=0)

        assert "error" in result
        mock_client.query_metric_set.assert_not_called()


# =========================================================================
# Error issues and reports
# =========================================================================


class TestErrorSearchTools:
    """Test the vitals error search tools."""

    def test_search_error_issues_ranks_worst_first(self, mock_client: MagicMock) -> None:
        """Issues are searched over the trailing window, ranked by report count."""
        mock_client.search_error_issues.return_value = {"errorIssues": [{"name": "issue/1"}]}

        result = search_error_issues(PACKAGE, days=7, max_results=5)

        mock_client.search_error_issues.assert_called_once_with(
            package_name=PACKAGE,
            start_date=result["start_date"],
            end_date=result["end_date"],
            filter_expression=None,
            order_by="errorReportCount desc",
            max_results=5,
        )
        assert result["issues"] == {"errorIssues": [{"name": "issue/1"}]}
        assert_trailing_window(result, 7)

    def test_search_error_reports_defaults_to_whole_app(self, mock_client: MagicMock) -> None:
        """Without an issue_id, reports are sampled across the app."""
        mock_client.search_error_reports.return_value = {"errorReports": []}

        result = search_error_reports(PACKAGE)

        assert mock_client.search_error_reports.call_args.kwargs["issue_id"] is None
        assert result["issue_id"] is None
        assert_trailing_window(result, DEFAULT_VITALS_DAYS)

    def test_search_error_reports_scoped_to_issue(self, mock_client: MagicMock) -> None:
        """An issue_id and a caller filter both reach the client for one issue."""
        mock_client.search_error_reports.return_value = {"errorReports": [{"name": "report/1"}]}

        result = search_error_reports(
            PACKAGE,
            issue_id="issue/1",
            filter_expression="versionCode = 42",
            max_results=3,
        )

        mock_client.search_error_reports.assert_called_once_with(
            package_name=PACKAGE,
            issue_id="issue/1",
            start_date=result["start_date"],
            end_date=result["end_date"],
            filter_expression="versionCode = 42",
            max_results=3,
        )
        assert result["issue_id"] == "issue/1"
        assert result["reports"] == {"errorReports": [{"name": "report/1"}]}

    @pytest.mark.parametrize("tool", [search_error_issues, search_error_reports])
    def test_invalid_window_is_rejected(self, mock_client: MagicMock, tool: Any) -> None:
        """An out-of-range window returns an error without calling the API."""
        result = tool(PACKAGE, days=MAX_VITALS_DAYS + 1)

        assert "error" in result
        mock_client.search_error_issues.assert_not_called()
        mock_client.search_error_reports.assert_not_called()


# =========================================================================
# Anomalies and freshness
# =========================================================================


class TestAnomaliesAndFreshness:
    """Test the anomaly listing and metric freshness tools."""

    def test_list_anomalies_unfiltered_by_default(self, mock_client: MagicMock) -> None:
        """Without a window, every anomaly Play currently holds is listed."""
        mock_client.list_anomalies.return_value = {
            "anomalies": [{"metricSet": "crashRateMetricSet"}]
        }

        result = list_anomalies(PACKAGE)

        mock_client.list_anomalies.assert_called_once_with(
            package_name=PACKAGE,
            filter_expression=None,
            max_results=25,
        )
        assert result["package_name"] == PACKAGE
        assert result["filter"] is None
        assert result["anomalies"] == {"anomalies": [{"metricSet": "crashRateMetricSet"}]}

    def test_list_anomalies_window_becomes_active_between_filter(
        self, mock_client: MagicMock
    ) -> None:
        """A days window is expressed as the API's activeBetween filter."""
        mock_client.list_anomalies.return_value = {"anomalies": []}

        result = list_anomalies(PACKAGE, days=7)

        start = (datetime.now(UTC).date() - timedelta(days=7)).isoformat()
        assert result["filter"] == f'activeBetween("{start}T00:00:00Z", UNBOUNDED)'
        assert mock_client.list_anomalies.call_args.kwargs["filter_expression"] == result["filter"]

    def test_list_anomalies_rejects_invalid_window(self, mock_client: MagicMock) -> None:
        """An out-of-range window returns an error without calling the API."""
        result = list_anomalies(PACKAGE, days=0)

        assert "error" in result
        mock_client.list_anomalies.assert_not_called()

    @pytest.mark.parametrize("metric_set", REPORTING_METRIC_SETS)
    def test_get_metric_freshness_accepts_every_metric_set(
        self, mock_client: MagicMock, metric_set: str
    ) -> None:
        """Every documented metric set is queryable for freshness."""
        mock_client.get_metric_set_freshness.return_value = {"freshnessInfo": {}}

        result = get_metric_freshness(PACKAGE, metric_set)

        mock_client.get_metric_set_freshness.assert_called_once_with(
            package_name=PACKAGE,
            metric_set=metric_set,
        )
        assert result["metric_set"] == metric_set
        assert result["freshness"] == {"freshnessInfo": {}}

    def test_get_metric_freshness_rejects_unknown_metric_set(self, mock_client: MagicMock) -> None:
        """An unknown metric set returns an error listing the valid ones."""
        result = get_metric_freshness(PACKAGE, "bogusMetricSet")

        assert "error" in result
        assert "crashRateMetricSet" in result["error"]
        mock_client.get_metric_set_freshness.assert_not_called()


# =========================================================================
# Read-only posture and client contract
# =========================================================================


def test_vitals_tools_are_not_blocked_in_read_only(
    mock_client: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Reporting API has no write methods, so read-only mode must not gate it."""
    from play_store_mcp import server

    monkeypatch.setattr(server, "READ_ONLY", True)
    mock_client.query_metric_set.return_value = {"rows": []}

    result = get_crash_rate(PACKAGE)

    assert "error" not in result
    mock_client.query_metric_set.assert_called_once()


@pytest.mark.parametrize(
    ("client_method", "tool", "kwargs"),
    [
        ("query_metric_set", get_crash_rate, {"package_name": PACKAGE}),
        ("query_metric_set", get_vitals_summary, {"package_name": PACKAGE}),
        ("search_error_issues", search_error_issues, {"package_name": PACKAGE}),
        (
            "search_error_reports",
            search_error_reports,
            {"package_name": PACKAGE, "issue_id": "issue/1"},
        ),
        ("list_anomalies", list_anomalies, {"package_name": PACKAGE}),
        (
            "get_metric_set_freshness",
            get_metric_freshness,
            {"package_name": PACKAGE, "metric_set": "crashRateMetricSet"},
        ),
    ],
)
def test_tool_calls_match_client_signatures(
    mock_client: MagicMock, client_method: str, tool: Any, kwargs: dict[str, Any]
) -> None:
    """Every argument these tools pass must bind to the real client signature.

    The tool layer and the reporting client methods landed as separate changes;
    this catches a drifted keyword before it becomes a runtime TypeError.
    """
    method = getattr(PlayStoreClient, client_method, None)
    if method is None:
        pytest.skip(f"PlayStoreClient.{client_method} is not implemented yet")

    signature = inspect.signature(method)
    mock_client.query_metric_set.return_value = {"rows": []}

    tool(**kwargs)

    for call in getattr(mock_client, client_method).call_args_list:
        signature.bind(MagicMock(), *call.args, **call.kwargs)


# =========================================================================
# Window validation across every windowed tool
# =========================================================================


@pytest.mark.parametrize(
    "tool",
    [
        get_crash_rate,
        get_anr_rate,
        get_excessive_wakeup_rate,
        get_slow_start_rate,
        get_vitals_summary,
        search_error_issues,
        search_error_reports,
        list_anomalies,
    ],
)
@pytest.mark.parametrize("days", [0, -1, MAX_VITALS_DAYS + 1])
def test_every_windowed_tool_rejects_an_invalid_window(
    mock_client: MagicMock, tool: Any, days: int
) -> None:
    """No tool may reach the API with a window the Reporting API cannot serve."""
    result = tool(PACKAGE, days=days)

    assert "days must be between" in result["error"]
    assert mock_client.method_calls == []


# =========================================================================
# Empty data and permission failures, as an MCP caller sees them
# =========================================================================


class TestEmptyAndDeniedThroughTheToolLayer:
    """The client's empty-result note and 403 diagnosis must survive the tools."""

    @pytest.mark.parametrize(
        ("tool", "client_method", "payload_key", "result_key"),
        [
            (get_crash_rate, "query_metric_set", "rows", "data"),
            (get_anr_rate, "query_metric_set", "rows", "data"),
            (get_excessive_wakeup_rate, "query_metric_set", "rows", "data"),
            (get_slow_start_rate, "query_metric_set", "rows", "data"),
            (search_error_issues, "search_error_issues", "errorIssues", "issues"),
            (search_error_reports, "search_error_reports", "errorReports", "reports"),
            (list_anomalies, "list_anomalies", "anomalies", "anomalies"),
        ],
    )
    def test_no_data_is_an_empty_but_valid_result(
        self,
        mock_client: MagicMock,
        tool: Any,
        client_method: str,
        payload_key: str,
        result_key: str,
    ) -> None:
        """An app with no vitals data returns an annotated payload, not an error."""
        empty = {payload_key: [], "note": f"No {payload_key} returned for {PACKAGE}."}
        getattr(mock_client, client_method).return_value = empty

        result = tool(PACKAGE)

        assert "error" not in result
        assert result[result_key] == empty
        assert result[result_key][payload_key] == []

    def test_summary_reports_three_empty_timelines_without_failing(
        self, mock_client: MagicMock
    ) -> None:
        empty = {"rows": [], "note": f"No rows returned for {PACKAGE}."}
        mock_client.query_metric_set.return_value = empty

        result = get_vitals_summary(PACKAGE)

        assert "error" not in result
        assert result["crash_rate"] == empty
        assert result["anr_rate"] == empty
        assert result["slow_start_rate"] == empty

    def test_freshness_with_no_data_is_returned_as_is(self, mock_client: MagicMock) -> None:
        empty = {"note": f"No freshnessInfo returned for {PACKAGE}."}
        mock_client.get_metric_set_freshness.return_value = empty

        result = get_metric_freshness(PACKAGE, "crashRateMetricSet")

        assert "error" not in result
        assert result["freshness"] == empty

    @pytest.mark.parametrize(
        ("tool", "client_method"),
        [
            (get_crash_rate, "query_metric_set"),
            (get_vitals_summary, "query_metric_set"),
            (search_error_issues, "search_error_issues"),
            (search_error_reports, "search_error_reports"),
            (list_anomalies, "list_anomalies"),
        ],
    )
    def test_missing_permission_surfaces_the_diagnosis(
        self, mock_client: MagicMock, tool: Any, client_method: str
    ) -> None:
        """A 403 reaches the caller as the client's guidance, not a raw traceback."""
        denied = PlayStoreClientError(
            f"Failed to read vitals: access to {PACKAGE} was denied. The service account most "
            "likely lacks the Play Console permission CAN_VIEW_APP_QUALITY for this app."
        )
        getattr(mock_client, client_method).side_effect = denied

        with pytest.raises(PlayStoreClientError) as excinfo:
            tool(PACKAGE)

        message = str(excinfo.value)
        assert "CAN_VIEW_APP_QUALITY" in message
        assert PACKAGE in message

    def test_freshness_missing_permission_surfaces_the_diagnosis(
        self, mock_client: MagicMock
    ) -> None:
        mock_client.get_metric_set_freshness.side_effect = PlayStoreClientError(
            "Failed to get freshness for crashRateMetricSet: access to "
            f"{PACKAGE} was denied. ... CAN_VIEW_APP_QUALITY ..."
        )

        with pytest.raises(PlayStoreClientError, match="CAN_VIEW_APP_QUALITY"):
            get_metric_freshness(PACKAGE, "crashRateMetricSet")


# =========================================================================
# Quota safety, counted at the transport
# =========================================================================


def _reporting_client(service: MagicMock) -> PlayStoreClient:
    """A real client wired to a mock Reporting service, bypassing discovery."""
    client = PlayStoreClient(credentials_json={"type": "service_account"})
    client._reporting_service = service
    return client


def _round_trips(service: MagicMock) -> int:
    """API round trips made against the mock Reporting service."""
    return sum(1 for call in service.mock_calls if call[0].endswith("execute"))


def test_vitals_summary_makes_exactly_three_round_trips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The quota property, pinned end to end rather than at the mock client.

    The Reporting API allows roughly 10 QPS. Counting at the transport catches a
    regression the call-count test cannot: a summary that still made three
    ``query_metric_set`` calls but paged or fanned out underneath would show up
    here as more than three requests.

    Freshness probing is the one addition this budget deliberately allows, and
    only on a cold cache. It was previously counted as a regression -- but the
    three round trips it was protecting were three *failures*: the clock-derived
    end bound exceeded the metric sets' freshness ceiling and every query 400'd.
    Six requests that answer beat three that cannot. The cache keeps the steady
    state at three, so the extra cost is paid once per package per TTL.
    """
    service = MagicMock()
    vitals = service.vitals.return_value
    vitals.crashrate.return_value.query.return_value.execute.return_value = {"rows": [{"c": 1}]}
    vitals.anrrate.return_value.query.return_value.execute.return_value = {"rows": [{"a": 1}]}
    vitals.slowstartrate.return_value.query.return_value.execute.return_value = {"rows": [{"s": 1}]}

    from play_store_mcp import server

    server._freshness_cache.clear()
    client = _reporting_client(service)
    monkeypatch.setattr(server, "get_client_from_context", lambda: client)

    result = get_vitals_summary(PACKAGE)

    # Cold: one freshness lookup per metric set, then the three queries.
    assert _round_trips(service) == 6

    # Warm: freshness is cached, so the steady state is the original budget.
    before = _round_trips(service)
    get_vitals_summary(PACKAGE)
    assert _round_trips(service) - before == 3
    server._freshness_cache.clear()
    assert result["crash_rate"]["rows"] == [{"c": 1}]
    assert result["anr_rate"]["rows"] == [{"a": 1}]
    assert result["slow_start_rate"]["rows"] == [{"s": 1}]

    # The summary stays inside its three metric sets: no wakeup, error, or
    # anomaly resource is touched, and no dimension breakdown is requested.
    dispatched = {call[0] for call in service.mock_calls}
    assert not any("excessivewakeuprate" in name for name in dispatched)
    assert not any("errors" in name for name in dispatched)
    assert not any("anomalies" in name for name in dispatched)
    for query in (
        vitals.crashrate.return_value.query,
        vitals.anrrate.return_value.query,
        vitals.slowstartrate.return_value.query,
    ):
        assert "dimensions" not in query.call_args.kwargs["body"]


def test_single_metric_tools_make_one_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    """A dimension breakdown is one query with dimensions, not a query per value.

    Cold, that is one freshness lookup plus the query; warm, the query alone. The
    property being pinned is that dimensions do not fan out -- three dimensions
    still cost one query, not one per dimension value.
    """
    service = MagicMock()
    service.vitals.return_value.crashrate.return_value.query.return_value.execute.return_value = {
        "rows": [{"c": 1}]
    }

    from play_store_mcp import server

    server._freshness_cache.clear()
    monkeypatch.setattr(server, "get_client_from_context", lambda: _reporting_client(service))

    get_crash_rate(PACKAGE, dimensions=["versionCode", "deviceModel", "countryCode"])

    assert _round_trips(service) == 2

    before = _round_trips(service)
    get_crash_rate(PACKAGE, dimensions=["versionCode", "deviceModel", "countryCode"])
    assert _round_trips(service) - before == 1

    server._freshness_cache.clear()
    body = service.vitals.return_value.crashrate.return_value.query.call_args.kwargs["body"]
    assert body["dimensions"] == ["versionCode", "deviceModel", "countryCode"]


# =========================================================================
# Freshness-derived windows
# =========================================================================


def _freshness(latest: date, aggregation_period: str = "DAILY") -> dict[str, Any]:
    """A freshnessInfo payload shaped like the live API's."""
    return {
        "freshnessInfo": {
            "freshnesses": [
                {
                    "aggregationPeriod": aggregation_period,
                    "latestEndTime": {
                        "year": latest.year,
                        "month": latest.month,
                        "day": latest.day,
                        "timeZone": {"id": "America/Los_Angeles"},
                    },
                }
            ]
        }
    }


class TestFreshnessDerivedWindow:
    """The metric-set query endpoint 400s on an end bound past a metric set's
    freshness, so the window is derived from the data rather than the clock.

    Measured live on 2026-07-29: crashRate/anrRate/slowStart/excessiveWakeup were
    fresh only to 07-28 while errorCount reached 07-29, so a single clock-derived
    end bound cannot be right for all of them.
    """

    @pytest.fixture(autouse=True)
    def _clear_cache(self) -> Any:
        from play_store_mcp import server

        server._freshness_cache.clear()
        yield
        server._freshness_cache.clear()

    def test_window_ends_at_the_metric_sets_freshness(self, mock_client: MagicMock) -> None:
        ceiling = datetime.now(UTC).date() - timedelta(days=3)
        mock_client.get_metric_set_freshness.return_value = _freshness(ceiling)
        mock_client.query_metric_set.return_value = {"rows": []}

        result = get_crash_rate(PACKAGE, days=7)

        assert result["end_date"] == ceiling.isoformat()
        assert result["start_date"] == (ceiling - timedelta(days=7)).isoformat()
        assert "window_note" in result
        kwargs = mock_client.query_metric_set.call_args.kwargs
        assert kwargs["end_date"] == ceiling.isoformat()

    def test_no_note_when_data_is_current(self, mock_client: MagicMock) -> None:
        """A window that already reaches today needs no explanation."""
        mock_client.get_metric_set_freshness.return_value = _freshness(datetime.now(UTC).date())
        mock_client.query_metric_set.return_value = {"rows": []}

        assert "window_note" not in get_crash_rate(PACKAGE, days=7)

    def test_summary_takes_the_oldest_ceiling_of_its_metric_sets(
        self, mock_client: MagicMock
    ) -> None:
        """One shared window across three metric sets must clear the strictest
        ceiling, or the whole call 400s on whichever set is furthest behind."""
        today = datetime.now(UTC).date()
        ceilings = {
            "crashRateMetricSet": today - timedelta(days=1),
            "anrRateMetricSet": today - timedelta(days=4),
            "slowStartRateMetricSet": today - timedelta(days=2),
        }
        mock_client.get_metric_set_freshness.side_effect = lambda metric_set, **_: _freshness(
            ceilings[metric_set]
        )
        mock_client.query_metric_set.return_value = {"rows": []}

        result = get_vitals_summary(PACKAGE, days=7)

        assert result["end_date"] == (today - timedelta(days=4)).isoformat()
        ends = {c.kwargs["end_date"] for c in mock_client.query_metric_set.call_args_list}
        assert ends == {result["end_date"]}

    def test_falls_back_to_a_day_back_when_freshness_errors(self, mock_client: MagicMock) -> None:
        """A freshness lookup that fails must not turn a working query into an error."""
        mock_client.get_metric_set_freshness.side_effect = PlayStoreClientError("no permission")
        mock_client.query_metric_set.return_value = {"rows": []}

        result = get_crash_rate(PACKAGE, days=7)

        assert result["end_date"] == (datetime.now(UTC).date() - timedelta(days=1)).isoformat()
        assert "window_note" in result

    def test_falls_back_when_no_daily_entry_is_published(self, mock_client: MagicMock) -> None:
        """Not every metric set reports every aggregation period."""
        mock_client.get_metric_set_freshness.return_value = _freshness(
            datetime.now(UTC).date(), aggregation_period="HOURLY"
        )
        mock_client.query_metric_set.return_value = {"rows": []}

        result = get_crash_rate(PACKAGE, days=7)

        assert result["end_date"] == (datetime.now(UTC).date() - timedelta(days=1)).isoformat()

    def test_freshness_is_cached_across_calls(self, mock_client: MagicMock) -> None:
        """Freshness moves at most hourly; paying a quota call per query is waste."""
        mock_client.get_metric_set_freshness.return_value = _freshness(
            datetime.now(UTC).date() - timedelta(days=1)
        )
        mock_client.query_metric_set.return_value = {"rows": []}

        get_crash_rate(PACKAGE, days=7)
        get_crash_rate(PACKAGE, days=14)

        assert mock_client.get_metric_set_freshness.call_count == 1


# Verbatim freshnessInfo payloads recorded from the live Play Developer Reporting
# API on 2026-07-29. Kept as fixtures because the shape carries three traps that
# a hand-written mock would not reproduce: HOURLY can precede DAILY, a DAILY
# entry may itself carry an `hours` field, and some metric sets publish no HOURLY
# entry at all.
LIVE_FRESHNESS: dict[str, dict[str, Any]] = {
    "crashRateMetricSet": {
        "freshnessInfo": {
            "freshnesses": [
                {
                    "aggregationPeriod": "HOURLY",
                    "latestEndTime": {"year": 2026, "month": 7, "day": 29, "hours": 11},
                },
                {
                    "aggregationPeriod": "DAILY",
                    "latestEndTime": {"year": 2026, "month": 7, "day": 28},
                },
            ]
        }
    },
    "slowStartRateMetricSet": {
        "freshnessInfo": {
            "freshnesses": [
                {
                    "aggregationPeriod": "DAILY",
                    "latestEndTime": {"year": 2026, "month": 7, "day": 28},
                }
            ]
        }
    },
    "errorCountMetricSet": {
        "freshnessInfo": {
            "freshnesses": [
                {
                    "aggregationPeriod": "HOURLY",
                    "latestEndTime": {"year": 2026, "month": 7, "day": 29, "hours": 13},
                },
                {
                    "aggregationPeriod": "DAILY",
                    "latestEndTime": {"year": 2026, "month": 7, "day": 29, "hours": 6},
                },
                {
                    "aggregationPeriod": "FULL_RANGE",
                    "latestEndTime": {"year": 2026, "month": 7, "day": 29, "hours": 6},
                },
            ]
        }
    },
}


@pytest.mark.parametrize(
    ("metric_set", "expected"),
    [
        ("crashRateMetricSet", date(2026, 7, 28)),
        ("slowStartRateMetricSet", date(2026, 7, 28)),
        # Fresher than the rate metric sets, and its DAILY entry carries an hour.
        # The calendar date is the bound; the hour is how far into it aggregation ran.
        ("errorCountMetricSet", date(2026, 7, 29)),
    ],
)
def test_live_freshness_payloads_yield_the_ceiling_the_api_enforces(
    mock_client: MagicMock, metric_set: str, expected: date
) -> None:
    """Recorded responses must produce the same bound the API named in its 400:
    "'timeline_spec.end_date' field should be at most the current freshness
    2026-07-28 00:00". Anchoring on the clock instead 400s on every call."""
    from play_store_mcp import server

    server._freshness_cache.clear()
    mock_client.credentials_fingerprint = "acct"
    mock_client.get_metric_set_freshness.return_value = LIVE_FRESHNESS[metric_set]

    assert server._latest_daily_end(mock_client, PACKAGE, metric_set) == expected

    server._freshness_cache.clear()


class TestFreshnessCacheHygiene:
    """Properties of the cache itself, all three raised in review."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self) -> Any:
        from play_store_mcp import server

        server._freshness_cache.clear()
        yield
        server._freshness_cache.clear()

    def test_cache_is_scoped_to_the_credentials(self) -> None:
        """Credentials arrive per request, so one account's failure must not be
        served to another. Without the credential term in the key, an account
        without the app-quality permission caches None and an authorized account
        silently inherits the fallback -- and the 400 this module exists to avoid."""
        from play_store_mcp import server

        denied = MagicMock()
        denied.credentials_fingerprint = "acct-denied"
        denied.get_metric_set_freshness.side_effect = PlayStoreClientError("no permission")

        allowed = MagicMock()
        allowed.credentials_fingerprint = "acct-allowed"
        ceiling = datetime.now(UTC).date() - timedelta(days=3)
        allowed.get_metric_set_freshness.return_value = _freshness(ceiling)

        assert server._latest_daily_end(denied, PACKAGE, "crashRateMetricSet") is None
        assert server._latest_daily_end(allowed, PACKAGE, "crashRateMetricSet") == ceiling
        allowed.get_metric_set_freshness.assert_called_once()

    def test_expired_entries_are_evicted_not_merely_ignored(self) -> None:
        """A TTL checked only on read leaves every key resident forever, and
        package_name is caller-supplied."""
        from play_store_mcp import server

        client = MagicMock()
        client.credentials_fingerprint = "acct"
        client.get_metric_set_freshness.return_value = _freshness(datetime.now(UTC).date())

        server._latest_daily_end(client, "com.old.app", "crashRateMetricSet")
        assert len(server._freshness_cache) == 1

        # Age the existing entry past the TTL, then touch a different key.
        stale_key = next(iter(server._freshness_cache))
        stamp, value, ttl = server._freshness_cache[stale_key]
        server._freshness_cache[stale_key] = (stamp - ttl - 1, value, ttl)

        server._latest_daily_end(client, "com.new.app", "crashRateMetricSet")

        assert stale_key not in server._freshness_cache
        assert len(server._freshness_cache) == 1

    def test_cache_is_capped(self) -> None:
        """Distinct packages arriving faster than the TTL still cannot grow forever."""
        from play_store_mcp import server

        client = MagicMock()
        client.credentials_fingerprint = "acct"
        client.get_metric_set_freshness.return_value = _freshness(datetime.now(UTC).date())

        for i in range(server._FRESHNESS_CACHE_MAX + 25):
            server._latest_daily_end(client, f"com.example.app{i}", "crashRateMetricSet")

        assert len(server._freshness_cache) <= server._FRESHNESS_CACHE_MAX

    def test_summary_does_not_claim_a_window_it_could_not_verify(
        self, mock_client: MagicMock
    ) -> None:
        """If one of the three ceilings is unreadable, the minimum of the other
        two is not known to be safe for it -- it may lag further. Clamp to the
        conservative floor and say the window is unverified."""

        today = datetime.now(UTC).date()
        # Both readable ceilings are NEWER than the conservative floor, so
        # min(known) and min(known + floor) differ. Anything less and this test
        # passes against the bug it exists to catch.
        known = {
            "crashRateMetricSet": today,
            "anrRateMetricSet": today,
        }

        def _freshness_or_fail(metric_set: str, **_: Any) -> dict[str, Any]:
            if metric_set not in known:
                raise PlayStoreClientError("no permission")
            return _freshness(known[metric_set])

        mock_client.credentials_fingerprint = "acct"
        mock_client.get_metric_set_freshness.side_effect = _freshness_or_fail
        mock_client.query_metric_set.return_value = {"rows": []}

        result = get_vitals_summary(PACKAGE, days=7)

        assert result["end_date"] == (today - timedelta(days=1)).isoformat()
        assert "slowStartRateMetricSet" in result["window_note"]
        assert "unverified" in result["window_note"] or "conservative" in result["window_note"]


class TestFreshnessClientAndConcurrency:
    """The second review round: client reuse, transient failures, and races."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self) -> Any:
        from play_store_mcp import server

        server._freshness_cache.clear()
        yield
        server._freshness_cache.clear()

    def _client(self, ceiling: date | None = None) -> MagicMock:
        client = MagicMock()
        client.credentials_fingerprint = "acct"
        client.get_metric_set_freshness.return_value = _freshness(
            ceiling or datetime.now(UTC).date()
        )
        client.query_metric_set.return_value = {"rows": []}
        return client

    def test_one_client_serves_freshness_and_queries(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With per-request credentials each resolve builds a PlayStoreClient that
        reloads credentials and refetches discovery, so a cold summary asking for
        its own would construct four."""
        from play_store_mcp import server

        client = self._client()
        calls = {"n": 0}

        def _resolve() -> MagicMock:
            calls["n"] += 1
            return client

        monkeypatch.setattr(server, "get_client_from_context", _resolve)

        get_vitals_summary(PACKAGE, days=7)
        assert calls["n"] == 1

        calls["n"] = 0
        get_crash_rate(PACKAGE, days=7)
        assert calls["n"] == 1

    def test_transient_failures_get_a_short_lifetime(self) -> None:
        """A 429 or a dropped connection is not evidence that this metric set has
        no ceiling. Caching it for the full TTL pins a quarter hour of queries to
        the fallback bound -- and keeps 400ing anything lagging further."""
        from play_store_mcp import server

        client = MagicMock()
        client.credentials_fingerprint = "acct"
        client.get_metric_set_freshness.side_effect = PlayStoreClientError("429 rate limited")

        assert server._latest_daily_end(client, PACKAGE, "crashRateMetricSet") is None

        (_, value, ttl) = next(iter(server._freshness_cache.values()))
        assert value is None
        assert ttl == server._FRESHNESS_FAILURE_TTL_SECONDS
        assert ttl < server._FRESHNESS_TTL_SECONDS

    def test_a_valid_response_without_a_daily_entry_keeps_the_full_lifetime(self) -> None:
        """That one is a durable fact about the metric set, not a transient error."""
        from play_store_mcp import server

        client = MagicMock()
        client.credentials_fingerprint = "acct"
        client.get_metric_set_freshness.return_value = _freshness(
            datetime.now(UTC).date(), aggregation_period="HOURLY"
        )

        assert server._latest_daily_end(client, PACKAGE, "crashRateMetricSet") is None

        (_, value, ttl) = next(iter(server._freshness_cache.values()))
        assert value is None
        assert ttl == server._FRESHNESS_TTL_SECONDS

    def test_concurrent_lookups_do_not_corrupt_the_cache(self) -> None:
        """The tools are sync callables, so HTTP transports run them in a worker
        pool. Unsynchronised, pruning iterates a dict another worker is inserting
        into: "dictionary changed size during iteration"."""
        import threading

        from play_store_mcp import server

        client = self._client()
        errors: list[BaseException] = []
        start = threading.Barrier(8)

        def hammer(worker: int) -> None:
            try:
                start.wait()
                for i in range(150):
                    server._latest_daily_end(
                        client, f"com.example.w{worker}.app{i}", "crashRateMetricSet"
                    )
            except BaseException as exc:
                errors.append(exc)

        threads = [threading.Thread(target=hammer, args=(w,)) for w in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert not errors, f"{type(errors[0]).__name__}: {errors[0]}"
        assert len(server._freshness_cache) <= server._FRESHNESS_CACHE_MAX


def test_a_failed_lookup_never_overwrites_a_concurrent_success() -> None:
    """Two workers can miss the same key and both fetch outside the lock. If one
    succeeds and the other fails, the failure must not win by finishing last --
    that discards a just-fetched ceiling and pins the next 60s to the fallback.

    The interleaving is forced rather than hoped for: the losing lookup completes
    the winning one from inside its own network call, then raises. Calling them
    in sequence would not exercise this at all -- the second would simply read
    the warm cache and never reach the write path.
    """
    from play_store_mcp import server

    server._freshness_cache.clear()
    ceiling = datetime.now(UTC).date() - timedelta(days=3)

    winner = MagicMock()
    winner.credentials_fingerprint = "acct"
    winner.get_metric_set_freshness.return_value = _freshness(ceiling)

    loser = MagicMock()
    loser.credentials_fingerprint = "acct"

    def _winner_lands_then_fail(**_: Any) -> dict[str, Any]:
        server._latest_daily_end(winner, PACKAGE, "crashRateMetricSet")
        raise PlayStoreClientError("429 rate limited")

    loser.get_metric_set_freshness.side_effect = _winner_lands_then_fail

    # The loser misses the cache, and the winner's success lands mid-flight.
    assert server._latest_daily_end(loser, PACKAGE, "crashRateMetricSet") == ceiling

    (_, value, ttl) = next(iter(server._freshness_cache.values()))
    assert value == ceiling
    assert ttl == server._FRESHNESS_TTL_SECONDS
    server._freshness_cache.clear()

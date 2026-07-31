"""Tests for the Play Developer Reporting API client (Android vitals)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from googleapiclient.errors import HttpError

from play_store_mcp.client import (
    _REPORTING_DEFAULT_WINDOW_DAYS,
    REPORTING_API_NAME,
    REPORTING_API_VERSION,
    REPORTING_METRIC_SETS,
    SCOPES,
    PlayStoreClient,
    PlayStoreClientError,
)

PACKAGE = "com.example.app"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_http_error(status: int, reason: str = "boom") -> HttpError:
    resp = MagicMock()
    resp.status = status
    resp.reason = reason
    err = HttpError(resp, b"{}")
    err.reason = reason
    return err


def _client(service: MagicMock) -> PlayStoreClient:
    """Client wired to a mock reporting service, bypassing discovery."""
    client = PlayStoreClient(credentials_json={"type": "service_account"})
    client._reporting_service = service
    return client


def _crashrate(service: MagicMock) -> MagicMock:
    return service.vitals.return_value.crashrate.return_value


def _counts(service: MagicMock) -> MagicMock:
    return service.vitals.return_value.errors.return_value.counts.return_value


def _issues(service: MagicMock) -> MagicMock:
    return service.vitals.return_value.errors.return_value.issues.return_value


def _reports(service: MagicMock) -> MagicMock:
    return service.vitals.return_value.errors.return_value.reports.return_value


def _anomalies(service: MagicMock) -> MagicMock:
    return service.anomalies.return_value


def _pages(*responses: dict[str, Any]) -> list[dict[str, Any]]:
    """Sequential execute() results, one per page."""
    return list(responses)


# ---------------------------------------------------------------------------
# Scopes and service construction
# ---------------------------------------------------------------------------


def test_scopes_include_publishing_and_reporting() -> None:
    """Both APIs are addressed by one credential, so both scopes are requested."""
    assert "https://www.googleapis.com/auth/androidpublisher" in SCOPES
    assert "https://www.googleapis.com/auth/playdeveloperreporting" in SCOPES


def test_reporting_service_builds_separate_api() -> None:
    """The reporting service is its own discovery build, not the publishing one."""
    client = PlayStoreClient(credentials_json={"type": "service_account"})

    with (
        patch("play_store_mcp.client.service_account.Credentials.from_service_account_info"),
        patch("play_store_mcp.client.build") as mock_build,
    ):
        mock_build.side_effect = lambda name, version, **_kwargs: f"{name}/{version}"

        publishing = client._get_service()
        reporting = client._get_reporting_service()

    assert publishing == "androidpublisher/v3"
    assert reporting == "playdeveloperreporting/v1beta1"


def test_reporting_service_is_cached() -> None:
    """A second call reuses the built service instead of re-running discovery."""
    client = PlayStoreClient(credentials_json={"type": "service_account"})

    with (
        patch("play_store_mcp.client.service_account.Credentials.from_service_account_info"),
        patch("play_store_mcp.client.build") as mock_build,
    ):
        mock_build.return_value = MagicMock()

        first = client._get_reporting_service()
        second = client._get_reporting_service()

    assert first is second
    assert mock_build.call_count == 1


def test_reporting_service_requires_credentials() -> None:
    """Missing credentials fail the same way as for the publishing service."""
    client = PlayStoreClient(credentials_path="/nonexistent/path.json")

    with pytest.raises(PlayStoreClientError, match="No valid credentials found"):
        client._get_reporting_service()


# ---------------------------------------------------------------------------
# get_metric_set_freshness
# ---------------------------------------------------------------------------


def test_get_metric_set_freshness_success() -> None:
    service = MagicMock()
    _crashrate(service).get.return_value.execute.return_value = {
        "name": f"apps/{PACKAGE}/crashRateMetricSet",
        "freshnessInfo": {"freshnesses": [{"aggregationPeriod": "DAILY"}]},
    }

    result = _client(service).get_metric_set_freshness(PACKAGE, "crashRateMetricSet")

    _crashrate(service).get.assert_called_once_with(name=f"apps/{PACKAGE}/crashRateMetricSet")
    assert result["freshnessInfo"]["freshnesses"][0]["aggregationPeriod"] == "DAILY"
    assert "note" not in result


def test_get_metric_set_freshness_routes_error_counts_to_its_own_resource() -> None:
    """errorCountMetricSet lives under vitals.errors.counts, not its own top resource."""
    service = MagicMock()
    _counts(service).get.return_value.execute.return_value = {"freshnessInfo": {}}

    _client(service).get_metric_set_freshness(PACKAGE, "errorCountMetricSet")

    _counts(service).get.assert_called_once_with(name=f"apps/{PACKAGE}/errorCountMetricSet")


def test_get_metric_set_freshness_rejects_unknown_metric_set() -> None:
    service = MagicMock()

    with pytest.raises(PlayStoreClientError, match="Unknown metric set 'bogusMetricSet'"):
        _client(service).get_metric_set_freshness(PACKAGE, "bogusMetricSet")


def test_every_advertised_metric_set_resolves() -> None:
    """REPORTING_METRIC_SETS is the documented input, so all of it must work."""
    service = MagicMock()
    client = _client(service)

    for metric_set in REPORTING_METRIC_SETS:
        client._reporting_metric_set_resource(metric_set)


# ---------------------------------------------------------------------------
# query_metric_set
# ---------------------------------------------------------------------------


def test_query_metric_set_builds_request() -> None:
    service = MagicMock()
    _crashrate(service).query.return_value.execute.return_value = {"rows": [{"metrics": []}]}

    result = _client(service).query_metric_set(
        package_name=PACKAGE,
        metric_set="crashRateMetricSet",
        metrics=["crashRate", "distinctUsers"],
        dimensions=["versionCode"],
        start_date="2026-01-01",
        end_date="2026-01-08",
        aggregation_period="DAILY",
        filter_expression="versionCode = 123",
        user_cohort="OS_PUBLIC",
        max_results=25,
    )

    _crashrate(service).query.assert_called_once_with(
        name=f"apps/{PACKAGE}/crashRateMetricSet",
        body={
            "metrics": ["crashRate", "distinctUsers"],
            "dimensions": ["versionCode"],
            "timelineSpec": {
                "aggregationPeriod": "DAILY",
                "startTime": {"year": 2026, "month": 1, "day": 1},
                "endTime": {"year": 2026, "month": 1, "day": 8},
            },
            "filter": "versionCode = 123",
            "userCohort": "OS_PUBLIC",
            "pageSize": 25,
        },
    )
    assert result["rows"] == [{"metrics": []}]


def test_query_metric_set_hourly_carries_the_hour() -> None:
    """HOURLY points are identified by the hour, which DAILY points must omit."""
    service = MagicMock()
    _crashrate(service).query.return_value.execute.return_value = {"rows": [{}]}

    _client(service).query_metric_set(
        package_name=PACKAGE,
        metric_set="crashRateMetricSet",
        metrics=["crashRate"],
        start_date="2026-01-01T05",
        end_date="2026-01-01T09",
        aggregation_period="HOURLY",
    )

    timeline = _crashrate(service).query.call_args.kwargs["body"]["timelineSpec"]
    assert timeline["startTime"] == {"year": 2026, "month": 1, "day": 1, "hours": 5}
    assert timeline["endTime"] == {"year": 2026, "month": 1, "day": 1, "hours": 9}


def test_query_metric_set_always_sends_timeline_with_a_period() -> None:
    """The API rejects a missing timeline_spec and an unspecified aggregation
    period -- both verified live -- so the client must always send both."""
    service = MagicMock()
    _crashrate(service).query.return_value.execute.return_value = {"rows": [{}]}

    _client(service).query_metric_set(
        package_name=PACKAGE,
        metric_set="crashRateMetricSet",
        metrics=["crashRate"],
    )

    spec = _crashrate(service).query.call_args.kwargs["body"]["timelineSpec"]
    assert spec["aggregationPeriod"] == "DAILY"


def _timeline_bounds(service: MagicMock) -> tuple[date, date]:
    """The (start, end) the client actually put on the wire, as dates."""
    spec = _crashrate(service).query.call_args.kwargs["body"]["timelineSpec"]
    return (
        date(**{k: v for k, v in spec["startTime"].items() if k != "hours"}),
        date(**{k: v for k, v in spec["endTime"].items() if k != "hours"}),
    )


def test_query_metric_set_default_window_anchors_on_a_supplied_end_date() -> None:
    """A caller who gives only end_date gets a window ending there.

    Regression: the default start was derived from the clock even when the
    caller supplied end_date, so any historical end_date produced start > end --
    an inverted range the API rejects.
    """
    service = MagicMock()
    _crashrate(service).query.return_value.execute.return_value = {"rows": []}

    _client(service).query_metric_set(
        package_name=PACKAGE,
        metric_set="crashRateMetricSet",
        metrics=["crashRate"],
        end_date="2026-06-01",
    )

    start, end = _timeline_bounds(service)
    assert end == date(2026, 6, 1)
    assert start == date(2026, 5, 4)
    assert start < end


def test_query_metric_set_default_window_ends_a_day_back() -> None:
    """With neither bound given, the window ends yesterday -- today is still
    aggregating, and the API rejects an end past the current freshness."""
    service = MagicMock()
    _crashrate(service).query.return_value.execute.return_value = {"rows": []}

    _client(service).query_metric_set(
        package_name=PACKAGE,
        metric_set="crashRateMetricSet",
        metrics=["crashRate"],
    )

    start, end = _timeline_bounds(service)
    assert end == date.today() - timedelta(days=1)
    assert (end - start).days == _REPORTING_DEFAULT_WINDOW_DAYS
    assert start < end


@pytest.mark.parametrize("end_date", ["2026-06-01", "2026-06-01T09", "2020-01-01"])
def test_query_metric_set_never_builds_an_inverted_range(end_date: str) -> None:
    """No supplied end_date, however old, may produce start > end."""
    service = MagicMock()
    _crashrate(service).query.return_value.execute.return_value = {"rows": []}

    _client(service).query_metric_set(
        package_name=PACKAGE,
        metric_set="crashRateMetricSet",
        metrics=["crashRate"],
        end_date=end_date,
        aggregation_period="HOURLY" if "T" in end_date else "DAILY",
    )

    start, end = _timeline_bounds(service)
    assert start < end


def test_query_metric_set_rejects_hour_on_daily_aggregation() -> None:
    """The API rejects an hours field on a DAILY timeline; say so before spending a call."""
    service = MagicMock()

    with pytest.raises(PlayStoreClientError, match="DAILY aggregation expects a date"):
        _client(service).query_metric_set(
            package_name=PACKAGE,
            metric_set="crashRateMetricSet",
            metrics=["crashRate"],
            start_date="2026-01-01T05",
            aggregation_period="DAILY",
        )

    _crashrate(service).query.assert_not_called()


def test_query_metric_set_rejects_bad_date_format() -> None:
    service = MagicMock()

    with pytest.raises(PlayStoreClientError, match="Invalid start_date '01/02/2026'"):
        _client(service).query_metric_set(
            package_name=PACKAGE,
            metric_set="crashRateMetricSet",
            metrics=["crashRate"],
            start_date="01/02/2026",
        )


def test_query_metric_set_rejects_unknown_aggregation_period() -> None:
    service = MagicMock()

    with pytest.raises(PlayStoreClientError, match="Invalid aggregation_period 'WEEKLY'"):
        _client(service).query_metric_set(
            package_name=PACKAGE,
            metric_set="crashRateMetricSet",
            metrics=["crashRate"],
            aggregation_period="WEEKLY",
        )


def test_query_metric_set_requires_metrics() -> None:
    service = MagicMock()

    with pytest.raises(PlayStoreClientError, match="requires at least one metric"):
        _client(service).query_metric_set(
            package_name=PACKAGE,
            metric_set="crashRateMetricSet",
            metrics=[],
        )


def test_query_metric_set_rejects_user_cohort_on_error_counts() -> None:
    """QueryErrorCountMetricSetRequest has no userCohort field."""
    service = MagicMock()

    with pytest.raises(PlayStoreClientError, match="user_cohort is not supported"):
        _client(service).query_metric_set(
            package_name=PACKAGE,
            metric_set="errorCountMetricSet",
            metrics=["errorReportCount"],
            user_cohort="OS_BETA",
        )


def test_query_metric_set_paginates_up_to_max_results() -> None:
    service = MagicMock()
    _crashrate(service).query.return_value.execute.side_effect = _pages(
        {"rows": [{"i": 1}, {"i": 2}], "nextPageToken": "page-2"},
        {"rows": [{"i": 3}, {"i": 4}]},
    )

    result = _client(service).query_metric_set(
        package_name=PACKAGE,
        metric_set="crashRateMetricSet",
        metrics=["crashRate"],
        max_results=4,
    )

    assert result["rows"] == [{"i": 1}, {"i": 2}, {"i": 3}, {"i": 4}]
    assert "nextPageToken" not in result
    assert _crashrate(service).query.call_count == 2
    assert _crashrate(service).query.call_args_list[1].kwargs["body"]["pageToken"] == "page-2"


def test_query_metric_set_stops_at_max_results_and_reports_more() -> None:
    """Truncation has to be visible, or a partial timeline reads as the whole one."""
    service = MagicMock()
    _crashrate(service).query.return_value.execute.return_value = {
        "rows": [{"i": 1}, {"i": 2}],
        "nextPageToken": "page-2",
    }

    result = _client(service).query_metric_set(
        package_name=PACKAGE,
        metric_set="crashRateMetricSet",
        metrics=["crashRate"],
        max_results=2,
    )

    assert result["rows"] == [{"i": 1}, {"i": 2}]
    assert result["nextPageToken"] == "page-2"
    assert _crashrate(service).query.call_count == 1


def test_query_metric_set_requests_only_what_is_missing() -> None:
    """A small max_results must not ask for a full page of rows."""
    service = MagicMock()
    _crashrate(service).query.return_value.execute.return_value = {"rows": [{"i": 1}]}

    _client(service).query_metric_set(
        package_name=PACKAGE,
        metric_set="crashRateMetricSet",
        metrics=["crashRate"],
        max_results=3,
    )

    assert _crashrate(service).query.call_args.kwargs["body"]["pageSize"] == 3


def test_query_metric_set_rejects_zero_max_results() -> None:
    service = MagicMock()

    with pytest.raises(PlayStoreClientError, match="max_results must be at least 1"):
        _client(service).query_metric_set(
            package_name=PACKAGE,
            metric_set="crashRateMetricSet",
            metrics=["crashRate"],
            max_results=0,
        )


def test_query_metric_set_stops_on_an_empty_page_with_a_token() -> None:
    """A token that never runs out must not spin the pagination loop forever."""
    service = MagicMock()
    _crashrate(service).query.return_value.execute.return_value = {
        "rows": [],
        "nextPageToken": "always-more",
    }

    result = _client(service).query_metric_set(
        package_name=PACKAGE,
        metric_set="crashRateMetricSet",
        metrics=["crashRate"],
        max_results=100,
    )

    assert result["rows"] == []
    assert _crashrate(service).query.call_count == 1


def test_query_metric_set_retries_server_error() -> None:
    """The :query POST writes nothing, so a 503 is safe to retry."""
    service = MagicMock()
    _crashrate(service).query.return_value.execute.side_effect = [
        _make_http_error(503),
        {"rows": [{"i": 1}]},
    ]

    result = _client(service).query_metric_set(
        package_name=PACKAGE,
        metric_set="crashRateMetricSet",
        metrics=["crashRate"],
    )

    assert result["rows"] == [{"i": 1}]
    assert _crashrate(service).query.return_value.execute.call_count == 2


# ---------------------------------------------------------------------------
# Empty results and permission errors — the "why is vitals empty?" path
# ---------------------------------------------------------------------------


def test_empty_rows_are_annotated_with_likely_causes() -> None:
    service = MagicMock()
    _crashrate(service).query.return_value.execute.return_value = {"rows": []}

    result = _client(service).query_metric_set(
        package_name=PACKAGE,
        metric_set="crashRateMetricSet",
        metrics=["crashRate"],
    )

    assert result["rows"] == []
    assert PACKAGE in result["note"]
    assert "CAN_VIEW_APP_QUALITY" in result["note"]


def test_empty_freshness_is_annotated() -> None:
    service = MagicMock()
    _crashrate(service).get.return_value.execute.return_value = {"name": "apps/x"}

    result = _client(service).get_metric_set_freshness(PACKAGE, "crashRateMetricSet")

    assert "note" in result


def test_populated_results_are_not_annotated() -> None:
    service = MagicMock()
    _anomalies(service).list.return_value.execute.return_value = {"anomalies": [{"id": "a"}]}

    result = _client(service).list_anomalies(PACKAGE)

    assert "note" not in result


def test_forbidden_names_the_missing_permission() -> None:
    """A bare 403 is the single most common vitals failure; it must self-diagnose."""
    service = MagicMock()
    _crashrate(service).query.return_value.execute.side_effect = _make_http_error(403)

    with pytest.raises(PlayStoreClientError) as excinfo:
        _client(service).query_metric_set(
            package_name=PACKAGE,
            metric_set="crashRateMetricSet",
            metrics=["crashRate"],
        )

    message = str(excinfo.value)
    assert "CAN_VIEW_APP_QUALITY" in message
    assert PACKAGE in message
    assert "Play Console" in message


def test_unauthorized_names_the_missing_permission() -> None:
    service = MagicMock()
    _issues(service).search.return_value.execute.side_effect = _make_http_error(401)

    with pytest.raises(PlayStoreClientError, match="CAN_VIEW_APP_QUALITY"):
        _client(service).search_error_issues(PACKAGE)


def test_not_found_explains_the_package_name() -> None:
    service = MagicMock()
    _crashrate(service).get.return_value.execute.side_effect = _make_http_error(404)

    with pytest.raises(PlayStoreClientError, match="Check the package name"):
        _client(service).get_metric_set_freshness(PACKAGE, "crashRateMetricSet")


def test_quota_exhaustion_explains_the_fan_out_trap() -> None:
    service = MagicMock()
    _anomalies(service).list.return_value.execute.side_effect = _make_http_error(429)

    with pytest.raises(PlayStoreClientError, match="quota"):
        _client(service).list_anomalies(PACKAGE)


def test_other_errors_surface_the_api_reason() -> None:
    service = MagicMock()
    _crashrate(service).query.return_value.execute.side_effect = _make_http_error(
        400, "Invalid metric"
    )

    with pytest.raises(PlayStoreClientError, match="Invalid metric"):
        _client(service).query_metric_set(
            package_name=PACKAGE,
            metric_set="crashRateMetricSet",
            metrics=["nope"],
        )


# ---------------------------------------------------------------------------
# search_error_issues
# ---------------------------------------------------------------------------


def test_search_error_issues_builds_request() -> None:
    service = MagicMock()
    _issues(service).search.return_value.execute.return_value = {"errorIssues": [{"name": "i1"}]}

    result = _client(service).search_error_issues(
        package_name=PACKAGE,
        start_date="2026-01-01",
        end_date="2026-01-08",
        filter_expression="errorIssueType = CRASH",
        order_by="errorReportCount desc",
        sample_error_report_limit=1,
        max_results=10,
    )

    _issues(service).search.assert_called_once_with(
        parent=f"apps/{PACKAGE}",
        interval_startTime_year=2026,
        interval_startTime_month=1,
        interval_startTime_day=1,
        interval_endTime_year=2026,
        interval_endTime_month=1,
        interval_endTime_day=8,
        filter="errorIssueType = CRASH",
        orderBy="errorReportCount desc",
        sampleErrorReportLimit=1,
        pageSize=10,
    )
    assert result["errorIssues"] == [{"name": "i1"}]


def test_search_error_issues_omits_interval_when_no_dates_given() -> None:
    """No dates means the API's own default window, not a zeroed interval."""
    service = MagicMock()
    _issues(service).search.return_value.execute.return_value = {"errorIssues": []}

    _client(service).search_error_issues(PACKAGE)

    kwargs = _issues(service).search.call_args.kwargs
    assert not [key for key in kwargs if key.startswith("interval_")]


def test_search_error_issues_paginates() -> None:
    service = MagicMock()
    _issues(service).search.return_value.execute.side_effect = _pages(
        {"errorIssues": [{"i": 1}], "nextPageToken": "p2"},
        {"errorIssues": [{"i": 2}]},
    )

    result = _client(service).search_error_issues(PACKAGE, max_results=2)

    assert result["errorIssues"] == [{"i": 1}, {"i": 2}]
    assert _issues(service).search.call_args_list[1].kwargs["pageToken"] == "p2"


def test_search_error_issues_page_size_is_capped_at_the_api_limit() -> None:
    service = MagicMock()
    _issues(service).search.return_value.execute.return_value = {"errorIssues": []}

    _client(service).search_error_issues(PACKAGE, max_results=5000)

    assert _issues(service).search.call_args.kwargs["pageSize"] == 1000


# ---------------------------------------------------------------------------
# search_error_reports
# ---------------------------------------------------------------------------


def test_search_error_reports_scopes_to_an_issue() -> None:
    service = MagicMock()
    _reports(service).search.return_value.execute.return_value = {"errorReports": [{"r": 1}]}

    _client(service).search_error_reports(PACKAGE, issue_id="abc123")

    assert _reports(service).search.call_args.kwargs["filter"] == 'errorIssueId = "abc123"'


def test_search_error_reports_accepts_the_issue_resource_name() -> None:
    """The API returns issues as apps/{app}/{issue}, so that is what callers copy."""
    service = MagicMock()
    _reports(service).search.return_value.execute.return_value = {"errorReports": []}

    _client(service).search_error_reports(PACKAGE, issue_id=f"apps/{PACKAGE}/errorIssues/abc123")

    assert _reports(service).search.call_args.kwargs["filter"] == 'errorIssueId = "abc123"'


def test_search_error_reports_combines_issue_and_filter() -> None:
    service = MagicMock()
    _reports(service).search.return_value.execute.return_value = {"errorReports": []}

    _client(service).search_error_reports(
        PACKAGE,
        issue_id="abc123",
        filter_expression="versionCode = 5 OR versionCode = 6",
    )

    assert (
        _reports(service).search.call_args.kwargs["filter"]
        == 'errorIssueId = "abc123" AND versionCode = 5 OR versionCode = 6'
    )


def test_search_error_reports_escapes_quotes_in_the_issue_id() -> None:
    """An unescaped quote would end the literal and change the filter's meaning."""
    service = MagicMock()
    _reports(service).search.return_value.execute.return_value = {"errorReports": []}

    _client(service).search_error_reports(PACKAGE, issue_id='ab"c')

    assert _reports(service).search.call_args.kwargs["filter"] == 'errorIssueId = "ab\\"c"'


def test_search_error_reports_sends_no_filter_when_unscoped() -> None:
    service = MagicMock()
    _reports(service).search.return_value.execute.return_value = {"errorReports": []}

    _client(service).search_error_reports(PACKAGE)

    assert "filter" not in _reports(service).search.call_args.kwargs


def test_search_error_reports_page_size_is_capped_at_the_api_limit() -> None:
    service = MagicMock()
    _reports(service).search.return_value.execute.return_value = {"errorReports": []}

    _client(service).search_error_reports(PACKAGE, max_results=500)

    assert _reports(service).search.call_args.kwargs["pageSize"] == 100


def test_search_error_reports_paginates() -> None:
    """Reports cap at 100 per page, so any real triage window spans pages."""
    service = MagicMock()
    _reports(service).search.return_value.execute.side_effect = _pages(
        {"errorReports": [{"r": 1}], "nextPageToken": "p2"},
        {"errorReports": [{"r": 2}]},
    )

    result = _client(service).search_error_reports(PACKAGE, max_results=2)

    assert result["errorReports"] == [{"r": 1}, {"r": 2}]
    assert _reports(service).search.call_args_list[1].kwargs["pageToken"] == "p2"


def test_search_error_reports_reports_api_failure() -> None:
    service = MagicMock()
    _reports(service).search.return_value.execute.side_effect = _make_http_error(403)

    with pytest.raises(PlayStoreClientError, match="Failed to search error reports"):
        _client(service).search_error_reports(PACKAGE)


# ---------------------------------------------------------------------------
# list_anomalies
# ---------------------------------------------------------------------------


def test_list_anomalies_builds_request() -> None:
    service = MagicMock()
    _anomalies(service).list.return_value.execute.return_value = {"anomalies": [{"a": 1}]}

    result = _client(service).list_anomalies(
        PACKAGE,
        filter_expression='activeBetween("2026-01-01T00:00:00Z", UNBOUNDED)',
        max_results=3,
    )

    _anomalies(service).list.assert_called_once_with(
        parent=f"apps/{PACKAGE}",
        filter='activeBetween("2026-01-01T00:00:00Z", UNBOUNDED)',
        pageSize=3,
    )
    assert result["anomalies"] == [{"a": 1}]


def test_list_anomalies_page_size_is_capped_at_the_api_limit() -> None:
    service = MagicMock()
    _anomalies(service).list.return_value.execute.return_value = {"anomalies": []}

    _client(service).list_anomalies(PACKAGE, max_results=500)

    assert _anomalies(service).list.call_args.kwargs["pageSize"] == 100


def test_list_anomalies_paginates() -> None:
    service = MagicMock()
    _anomalies(service).list.return_value.execute.side_effect = _pages(
        {"anomalies": [{"a": 1}], "nextPageToken": "p2"},
        {"anomalies": [{"a": 2}]},
    )

    result = _client(service).list_anomalies(PACKAGE, max_results=2)

    assert result["anomalies"] == [{"a": 1}, {"a": 2}]
    assert _anomalies(service).list.call_args_list[1].kwargs["pageToken"] == "p2"


def test_list_anomalies_sends_no_filter_by_default() -> None:
    service = MagicMock()
    _anomalies(service).list.return_value.execute.return_value = {"anomalies": []}

    _client(service).list_anomalies(PACKAGE)

    assert "filter" not in _anomalies(service).list.call_args.kwargs


# ---------------------------------------------------------------------------
# Read-only guarantee
# ---------------------------------------------------------------------------


def test_reporting_client_exposes_no_write_methods() -> None:
    """The Reporting API defines no writes; the client must not invent one."""
    reporting_methods = [
        name
        for name in dir(PlayStoreClient)
        if name in {"get_metric_set_freshness", "query_metric_set", "list_anomalies"}
        or name.startswith("search_error")
    ]

    assert sorted(reporting_methods) == [
        "get_metric_set_freshness",
        "list_anomalies",
        "query_metric_set",
        "search_error_issues",
        "search_error_reports",
    ]


def test_no_reporting_call_invokes_a_mutating_method() -> None:
    """Stronger than the name check above: no write verb is ever dispatched.

    The method-name assertion only constrains what this client declares. This
    exercises every reporting call and asserts none of them reached a discovery
    method that could change state — the property that keeps the added
    playdeveloperreporting scope harmless.
    """
    service = MagicMock()
    _crashrate(service).get.return_value.execute.return_value = {"freshnessInfo": {}}
    _crashrate(service).query.return_value.execute.return_value = {"rows": [{"i": 1}]}
    _issues(service).search.return_value.execute.return_value = {"errorIssues": [{"i": 1}]}
    _reports(service).search.return_value.execute.return_value = {"errorReports": [{"r": 1}]}
    _anomalies(service).list.return_value.execute.return_value = {"anomalies": [{"a": 1}]}
    client = _client(service)

    client.get_metric_set_freshness(PACKAGE, "crashRateMetricSet")
    client.query_metric_set(PACKAGE, "crashRateMetricSet", ["crashRate"])
    client.search_error_issues(PACKAGE)
    client.search_error_reports(PACKAGE)
    client.list_anomalies(PACKAGE)

    dispatched = {call[0] for call in service.mock_calls}
    for verb in ("create", "insert", "update", "patch", "delete", "upload", "commit"):
        assert not any(name.endswith(f".{verb}") for name in dispatched), verb


# ---------------------------------------------------------------------------
# Service construction details
# ---------------------------------------------------------------------------


def test_reporting_api_identifiers_match_the_documented_api() -> None:
    assert REPORTING_API_NAME == "playdeveloperreporting"
    assert REPORTING_API_VERSION == "v1beta1"


def test_reporting_service_build_arguments() -> None:
    """Discovery is built for v1beta1, uncached, from both-scoped credentials."""
    client = PlayStoreClient(credentials_json={"type": "service_account"})

    with (
        patch(
            "play_store_mcp.client.service_account.Credentials.from_service_account_info"
        ) as mock_info,
        patch("play_store_mcp.client.build") as mock_build,
    ):
        mock_info.return_value = MagicMock()
        mock_build.return_value = MagicMock()

        client._get_reporting_service()

    args, kwargs = mock_build.call_args
    assert args[:2] == (REPORTING_API_NAME, REPORTING_API_VERSION)
    assert kwargs["cache_discovery"] is False
    assert mock_info.call_args.kwargs["scopes"] == SCOPES


def test_reporting_service_build_failure_is_wrapped() -> None:
    """A discovery failure surfaces as a client error naming the Reporting API."""
    client = PlayStoreClient(credentials_json={"type": "service_account"})

    with (
        patch("play_store_mcp.client.service_account.Credentials.from_service_account_info"),
        patch("play_store_mcp.client.build", side_effect=ValueError("no discovery doc")),
        pytest.raises(PlayStoreClientError, match="Failed to initialize Reporting API client"),
    ):
        client._get_reporting_service()


def test_reporting_service_does_not_satisfy_the_publishing_service() -> None:
    """Two APIs, two builds — one cache must never stand in for the other."""
    client = PlayStoreClient(credentials_json={"type": "service_account"})

    with (
        patch("play_store_mcp.client.service_account.Credentials.from_service_account_info"),
        patch("play_store_mcp.client.build") as mock_build,
    ):
        mock_build.side_effect = [MagicMock(), MagicMock()]

        reporting = client._get_reporting_service()
        publishing = client._get_service()

    assert reporting is not publishing
    assert [call.args[0] for call in mock_build.call_args_list] == [
        "playdeveloperreporting",
        "androidpublisher",
    ]


# ---------------------------------------------------------------------------
# Resource-name construction, across every metric set
# ---------------------------------------------------------------------------

# The discovery path each metric set is served by, and therefore the resource
# name its requests must carry. Written out here rather than imported from the
# client so a typo in the client's own mapping cannot make this agree with it.
_METRIC_SET_PATHS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("crashRateMetricSet", ("vitals", "crashrate")),
    ("anrRateMetricSet", ("vitals", "anrrate")),
    ("excessiveWakeupRateMetricSet", ("vitals", "excessivewakeuprate")),
    ("stuckBackgroundWakelockRateMetricSet", ("vitals", "stuckbackgroundwakelockrate")),
    ("slowStartRateMetricSet", ("vitals", "slowstartrate")),
    ("slowRenderingRateMetricSet", ("vitals", "slowrenderingrate")),
    ("lmkRateMetricSet", ("vitals", "lmkrate")),
    ("errorCountMetricSet", ("vitals", "errors", "counts")),
)


def _walk(service: MagicMock, path: tuple[str, ...]) -> MagicMock:
    """Resolve the discovery chain a metric set is reached through."""
    resource: MagicMock = service
    for attribute in path:
        resource = getattr(resource, attribute).return_value
    return resource


def test_metric_set_paths_cover_exactly_the_advertised_metric_sets() -> None:
    assert set(REPORTING_METRIC_SETS) == {metric_set for metric_set, _ in _METRIC_SET_PATHS}


def test_reporting_name_for_the_app_itself() -> None:
    assert PlayStoreClient._reporting_name(PACKAGE) == f"apps/{PACKAGE}"


def test_reporting_name_for_a_child_resource() -> None:
    assert (
        PlayStoreClient._reporting_name(PACKAGE, "crashRateMetricSet")
        == f"apps/{PACKAGE}/crashRateMetricSet"
    )


@pytest.mark.parametrize(("metric_set", "path"), _METRIC_SET_PATHS)
def test_freshness_names_the_metric_set_resource(metric_set: str, path: tuple[str, ...]) -> None:
    """Every metric set reads apps/{package}/{metricSet} from its own resource."""
    service = MagicMock()
    _walk(service, path).get.return_value.execute.return_value = {"freshnessInfo": {}}

    _client(service).get_metric_set_freshness(PACKAGE, metric_set)

    _walk(service, path).get.assert_called_once_with(name=f"apps/{PACKAGE}/{metric_set}")


@pytest.mark.parametrize(("metric_set", "path"), _METRIC_SET_PATHS)
def test_query_names_the_metric_set_resource(metric_set: str, path: tuple[str, ...]) -> None:
    service = MagicMock()
    _walk(service, path).query.return_value.execute.return_value = {"rows": [{"i": 1}]}

    _client(service).query_metric_set(PACKAGE, metric_set, ["distinctUsers"])

    assert _walk(service, path).query.call_args.kwargs["name"] == f"apps/{PACKAGE}/{metric_set}"


def test_unknown_metric_set_costs_no_api_call() -> None:
    """The name is validated locally, so a typo never spends quota."""
    service = MagicMock()

    with pytest.raises(PlayStoreClientError, match="Valid metric sets"):
        _client(service).query_metric_set(PACKAGE, "bogusMetricSet", ["crashRate"])

    assert not [call for call in service.mock_calls if call[0].endswith("execute")]


# ---------------------------------------------------------------------------
# Error-search intervals
# ---------------------------------------------------------------------------


def test_error_search_interval_carries_the_hour_when_given() -> None:
    """Search bounds are hour-precision, so an hourly bound must reach the API."""
    service = MagicMock()
    _issues(service).search.return_value.execute.return_value = {"errorIssues": []}

    _client(service).search_error_issues(PACKAGE, start_date="2026-01-01T05", end_date="2026-01-02")

    kwargs = _issues(service).search.call_args.kwargs
    assert kwargs["interval_startTime_hours"] == 5
    assert "interval_endTime_hours" not in kwargs


def test_error_reports_search_flattens_the_interval() -> None:
    service = MagicMock()
    _reports(service).search.return_value.execute.return_value = {"errorReports": []}

    _client(service).search_error_reports(PACKAGE, start_date="2026-01-01", end_date="2026-01-08")

    kwargs = _reports(service).search.call_args.kwargs
    assert kwargs["interval_startTime_year"] == 2026
    assert kwargs["interval_startTime_month"] == 1
    assert kwargs["interval_startTime_day"] == 1
    assert kwargs["interval_endTime_day"] == 8


def test_error_search_rejects_a_bad_interval_bound() -> None:
    service = MagicMock()

    with pytest.raises(PlayStoreClientError, match="Invalid end_date"):
        _client(service).search_error_issues(PACKAGE, end_date="last tuesday")


def test_query_metric_set_keeps_the_hour_when_deriving_an_hourly_start() -> None:
    """An HOURLY end_date must not lose its hour to the default start.

    Dropping it widened the window to 28 days plus that many hours, and the extra
    rows can displace requested ones once max_results is in play.
    """
    service = MagicMock()
    _crashrate(service).query.return_value.execute.return_value = {"rows": []}

    _client(service).query_metric_set(
        package_name=PACKAGE,
        metric_set="crashRateMetricSet",
        metrics=["crashRate"],
        end_date="2026-06-01T09",
        aggregation_period="HOURLY",
    )

    spec = _crashrate(service).query.call_args.kwargs["body"]["timelineSpec"]
    assert spec["endTime"] == {"year": 2026, "month": 6, "day": 1, "hours": 9}
    assert spec["startTime"] == {"year": 2026, "month": 5, "day": 4, "hours": 9}


def test_daily_with_hourly_end_date_blames_the_caller_s_field() -> None:
    """The DAILY-with-hour error must name end_date, not the synthesised start.

    Regression: when only an hourly end_date is given, the default start is
    derived from it. Carrying the hour onto that start made the validation loop
    — which checks startTime first — raise against `start_date`, a value the
    caller never supplied.
    """
    service = MagicMock()

    with pytest.raises(PlayStoreClientError) as excinfo:
        _client(service).query_metric_set(
            package_name=PACKAGE,
            metric_set="crashRateMetricSet",
            metrics=["crashRate"],
            end_date="2026-06-01T09",
            aggregation_period="DAILY",
        )

    message = str(excinfo.value)
    assert "end_date" in message
    assert "start_date" not in message
    assert "2026-06-01T09" in message

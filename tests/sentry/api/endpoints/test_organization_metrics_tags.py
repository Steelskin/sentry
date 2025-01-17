import time
from collections.abc import Collection
from datetime import timedelta
from unittest.mock import patch

import pytest

from sentry.sentry_metrics import indexer
from sentry.sentry_metrics.use_case_id_registry import UseCaseID
from sentry.snuba.metrics.naming_layer.mri import SessionMRI
from sentry.snuba.metrics.naming_layer.public import SessionMetricKey
from sentry.testutils.cases import MetricsAPIBaseTestCase, OrganizationMetricsIntegrationTestCase
from tests.sentry.api.endpoints.test_organization_metrics import MOCKED_DERIVED_METRICS

pytestmark = pytest.mark.sentry_metrics


def mocked_bulk_reverse_resolve(use_case_id, org_id: int, ids: Collection[int]):
    return {}


class OrganizationMetricsTagsTest(OrganizationMetricsIntegrationTestCase):
    endpoint = "sentry-api-0-organization-metrics-tags"

    @property
    def now(self):
        return MetricsAPIBaseTestCase.MOCK_DATETIME

    def test_metric_tags(self):
        response = self.get_success_response(
            self.organization.slug,
        )
        assert response.data == [
            {"key": "tag1"},
            {"key": "tag2"},
            {"key": "tag3"},
            {"key": "tag4"},
            {"key": "project"},
        ]

    def test_multiple_metrics_tags(self):
        response = self.get_response(
            self.organization.slug,
        )
        assert response.data == [
            {"key": "tag1"},
            {"key": "tag2"},
            {"key": "tag3"},
            {"key": "tag4"},
            {"key": "project"},
        ]

        response = self.get_response(
            self.organization.slug,
            metric=["d:transactions/duration@millisecond", "d:sessions/duration.exited@second"],
            useCase="transactions",
        )
        assert response.status_code == 400
        assert response.json()["detail"]["message"] == "Please provide only a single metric name."

    @patch(
        "sentry.snuba.metrics.datasource.bulk_reverse_resolve",
        mocked_bulk_reverse_resolve,
    )
    def test_unknown_tag(self):
        response = self.get_success_response(
            self.organization.slug,
        )
        assert response.data == [{"key": "project"}]

    def test_staff_session_metric_tags(self):
        staff_user = self.create_user(is_staff=True)
        self.login_as(user=staff_user, staff=True)

        self.store_session(
            self.build_session(
                project_id=self.project.id,
                started=(time.time() // 60) * 60,
                status="ok",
                release="foobar@2.0",
            )
        )
        response = self.get_success_response(
            self.organization.slug,
        )
        assert response.data == [
            {"key": "environment"},
            {"key": "release"},
            {"key": "tag1"},
            {"key": "tag2"},
            {"key": "tag3"},
            {"key": "tag4"},
            {"key": "project"},
        ]

    def test_session_metric_tags(self):
        self.store_session(
            self.build_session(
                project_id=self.project.id,
                started=(time.time() // 60) * 60,
                status="ok",
                release="foobar@2.0",
            )
        )
        response = self.get_success_response(
            self.organization.slug,
        )
        assert response.data == [
            {"key": "environment"},
            {"key": "release"},
            {"key": "tag1"},
            {"key": "tag2"},
            {"key": "tag3"},
            {"key": "tag4"},
            {"key": "project"},
        ]

    def test_metric_tags_metric_does_not_exist_in_naming_layer(self):
        response = self.get_response(
            self.organization.slug,
            metric=["foo.bar"],
        )
        assert response.data == []

    def test_metric_tags_metric_does_not_have_data(self):
        indexer.record(
            use_case_id=UseCaseID.SESSIONS,
            org_id=self.organization.id,
            string=SessionMRI.RAW_SESSION.value,
        )
        response = self.get_response(
            self.organization.slug,
            metric=[SessionMetricKey.CRASH_FREE_RATE.value],
        )
        assert (
            response.json()["detail"]
            == "The following metrics ['e:sessions/crash_free_rate@ratio'] do not exist in the dataset"
        )

        assert response.status_code == 404

    def test_derived_metric_tags(self):
        self.store_session(
            self.build_session(
                project_id=self.project.id,
                started=(time.time() // 60) * 60,
                status="ok",
                release="foobar@2.0",
            )
        )
        response = self.get_success_response(
            self.organization.slug,
            metric=["session.crash_free_rate"],
        )
        assert response.data == [{"key": "environment"}, {"key": "release"}, {"key": "project"}]

    def test_composite_derived_metrics(self):
        for minute in range(4):
            self.store_session(
                self.build_session(
                    project_id=self.project.id,
                    started=(time.time() // 60 - minute) * 60,
                    status="ok",
                    release="foobar@2.0",
                    errors=2,
                )
            )
        response = self.get_success_response(
            self.organization.slug,
            metric=[SessionMetricKey.HEALTHY.value],
        )
        assert response.data == [{"key": "environment"}, {"key": "release"}, {"key": "project"}]

    @patch("sentry.snuba.metrics.fields.base.DERIVED_METRICS", MOCKED_DERIVED_METRICS)
    @patch("sentry.snuba.metrics.datasource.get_mri")
    @patch("sentry.snuba.metrics.datasource.get_derived_metrics")
    def test_incorrectly_setup_derived_metric(self, mocked_derived_metrics, mocked_mri):
        mocked_mri.return_value = "crash_free_fake"
        mocked_derived_metrics.return_value = MOCKED_DERIVED_METRICS
        self.store_session(
            self.build_session(
                project_id=self.project.id,
                started=(time.time() // 60) * 60,
                status="ok",
                release="foobar@2.0",
                errors=2,
            )
        )
        response = self.get_response(
            self.organization.slug,
            metric=["crash_free_fake"],
        )
        assert response.status_code == 400
        assert response.json()["detail"] == (
            "The following metrics {'crash_free_fake'} cannot be computed from single entities. "
            "Please revise the definition of these singular entity derived metrics"
        )

    def test_metric_tags_with_date_range(self):
        mri = "c:custom/clicks@none"
        tags = (
            ("transaction", "/hello", 0),
            ("release", "1.0", 1),
            ("environment", "prod", 7),
        )
        for tag_name, tag_value, days in tags:
            self.store_metric(
                self.project.organization.id,
                self.project.id,
                "counter",
                mri,
                {tag_name: tag_value},
                int((self.now - timedelta(days=days)).timestamp()),
                10,
                UseCaseID.CUSTOM,
            )

        for stats_period, expected_count in (("1d", 2), ("2d", 3), ("2w", 4)):
            response = self.get_success_response(
                self.organization.slug,
                metric=[mri],
                project=self.project.id,
                useCase="custom",
                statsPeriod=stats_period,
            )
            assert len(response.data) == expected_count

    def test_metric_tags_with_gauge(self):
        mri = "g:custom/page_load@millisecond"
        self.store_metric(
            self.project.organization.id,
            self.project.id,
            "gauge",
            mri,
            {"transaction": "/hello", "release": "1.0", "environment": "prod"},
            int(self.now.timestamp()),
            10,
            UseCaseID.CUSTOM,
        )

        response = self.get_success_response(
            self.organization.slug,
            metric=[mri],
            project=self.project.id,
            useCase="custom",
        )
        assert len(response.data) == 4

    def test_metric_not_in_indexer(self):
        mri = "c:custom/sentry_metric@none"
        response = self.get_response(
            self.organization.slug,
            metric=[mri],
            project=self.project.id,
            useCase="custom",
        )
        assert (
            response.json()["detail"]
            == "One of the specified metrics was not found: ['c:custom/sentry_metric@none']"
        )
        assert response.status_code == 404

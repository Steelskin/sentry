from __future__ import annotations

import logging

import orjson
import requests
from django.conf import settings
from rest_framework.response import Response

from sentry import features
from sentry.api.api_owners import ApiOwner
from sentry.api.api_publish_status import ApiPublishStatus
from sentry.api.base import region_silo_endpoint
from sentry.api.bases.group import GroupEndpoint
from sentry.api.helpers.autofix import (
    AutofixCodebaseIndexingStatus,
    get_project_codebase_indexing_status,
)
from sentry.api.helpers.repos import get_repos_from_project_code_mappings
from sentry.integrations.utils.code_mapping import get_sorted_code_mapping_configs
from sentry.models.group import Group
from sentry.models.organization import Organization
from sentry.models.project import Project
from sentry.services.hybrid_cloud.integration import integration_service

logger = logging.getLogger(__name__)

from rest_framework.request import Request


def get_autofix_integration_setup_problems(
    organization: Organization, project: Project
) -> str | None:
    """
    Runs through the checks to see if we can use the GitHub integration for Autofix.

    If there are no issues, returns None.
    If there is an issue, returns the reason.
    """
    organization_integrations = integration_service.get_organization_integrations(
        organization_id=organization.id, providers=["github"], limit=1
    )

    organization_integration = organization_integrations[0] if organization_integrations else None
    integration = organization_integration and integration_service.get_integration(
        organization_integration_id=organization_integration.id
    )
    installation = integration and integration.get_installation(organization_id=organization.id)

    if not installation:
        return "integration_missing"

    code_mappings = get_sorted_code_mapping_configs(project)

    if not code_mappings:
        return "integration_no_code_mappings"

    return None


def get_repos_and_access(project: Project) -> list[dict]:
    """
    Gets the repos that would be indexed for the given project from the code mappings, and checks if we have write access to them.

    Returns a list of repos with the "ok" key set to True if we have write access, False otherwise.
    """
    repos = get_repos_from_project_code_mappings(project)

    repos_and_access: list[dict] = []
    for repo in repos:
        response = requests.post(
            f"{settings.SEER_AUTOFIX_URL}/v1/automation/codebase/repo/check-access",
            data=orjson.dumps(
                {
                    "repo": repo,
                }
            ),
            headers={"content-type": "application/json;charset=utf-8"},
        )

        response.raise_for_status()

        repos_and_access.append({**repo, "ok": response.json().get("has_access", False)})

    return repos_and_access


@region_silo_endpoint
class GroupAutofixSetupCheck(GroupEndpoint):
    publish_status = {
        "GET": ApiPublishStatus.EXPERIMENTAL,
    }
    owner = ApiOwner.ML_AI
    private = True

    def get(self, request: Request, group: Group) -> Response:
        """
        Checks if we are able to run Autofix on the given group.
        """
        if not features.has("projects:ai-autofix", group.project):
            return Response({"detail": "Feature not enabled for project"}, status=403)

        org: Organization = request.organization
        has_gen_ai_consent = org.get_option("sentry:gen_ai_consent", False)

        integration_check = get_autofix_integration_setup_problems(
            organization=org, project=group.project
        )

        repos = get_repos_and_access(group.project)
        write_access_ok = len(repos) > 0 and all(repo["ok"] for repo in repos)

        codebase_indexing_status = get_project_codebase_indexing_status(group.project)

        return Response(
            {
                "genAIConsent": {
                    "ok": has_gen_ai_consent,
                    "reason": None,
                },
                "integration": {
                    "ok": integration_check is None,
                    "reason": integration_check,
                },
                "githubWriteIntegration": {
                    "ok": write_access_ok,
                    "repos": repos,
                },
                "codebaseIndexing": {
                    "ok": codebase_indexing_status == AutofixCodebaseIndexingStatus.UP_TO_DATE
                    or codebase_indexing_status == AutofixCodebaseIndexingStatus.INDEXING,
                },
            }
        )

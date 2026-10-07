from typing import Any

from ..domain.exceptions import TenantIsolationViolationException
from ..security.context import RequestSecurityContext


class RetrievalTenantFilterGuard:
    """
    Enforces multi-tenant isolation at the Retrieval / OpenSearch / Vector Search layer.
    Ensures no vector or BM25 query can ever execute without a verified tenant_id boundary.
    """

    @staticmethod
    def inject_mandatory_tenant_filter(
        query_body: dict[str, Any],
        context: RequestSecurityContext,
        target_tenant_id: str
    ) -> dict[str, Any]:
        """
        Validates tenant context and injects non-overridable term filter into OpenSearch query.
        """
        if context.tenant_id != target_tenant_id:
            raise TenantIsolationViolationException(
                f"Retrieval layer breach: Caller tenant '{context.tenant_id}' cannot search target tenant '{target_tenant_id}'."
            )

        # Ensure bool filter structure exists
        if "query" not in query_body:
            query_body["query"] = {"bool": {}}
        if "bool" not in query_body["query"]:
            query_body["query"] = {"bool": {"must": [query_body["query"]]}}

        filter_clauses: list[dict[str, Any]] = query_body["query"]["bool"].get("filter", [])
        if isinstance(filter_clauses, dict):
            filter_clauses = [filter_clauses]

        # Inject compulsory tenant filter
        tenant_term = {"term": {"tenant_id": context.tenant_id}}
        filter_clauses.append(tenant_term)
        query_body["query"]["bool"]["filter"] = filter_clauses

        return query_body

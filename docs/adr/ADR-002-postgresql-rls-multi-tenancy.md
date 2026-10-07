# ADR-002: PostgreSQL with Row-Level Security (RLS) for Multi-Tenancy

## Status
Accepted

## Context
Serving 10 million registered users across thousands of enterprise financial tenants (banks, hedge funds, sovereign funds) requires ironclad data isolation. Financial regulations (SEC, FINRA, GDPR, SOC 2 Type II) strictly prohibit cross-tenant data leakage.

## Decision
We select **PostgreSQL (Amazon Aurora PostgreSQL Multi-AZ in production)** utilizing database-level **Row-Level Security (RLS)** as the primary multi-tenant transactional store.

## Why This Technology Was Selected
1. **Kernel-Level Enforcement**: Unlike application-level filtering (`WHERE tenant_id = x`), where a developer omission can leak data across tenants, PostgreSQL RLS enforces tenant boundaries in the database engine kernel. Even if application queries omit the filter, rows belonging to other tenants are invisible.
2. **Operational Scalability**: Separate database-per-tenant architectures for 10,000+ tenants incur crippling connection pool fragmentation, database connection exhaustion, and complex schema migration overhead. RLS provides tenant isolation inside shared, efficiently pooled relational tables.
3. **Transaction Integrity & ACID**: Complex multi-step operations (HITL audit logs, approval state transitions, user access grants) require robust ACID transactions and foreign key constraints.

## Implementation Details
1. Each request middleware extracts the authenticated `tenant_id`.
2. When acquiring a session from the connection pool, the connection sets session configuration:
   `SET LOCAL app.current_tenant_id = '<tenant_uuid>';`
3. RLS policies evaluate `current_setting('app.current_tenant_id')` to isolate rows.

## Alternatives Considered
- **Database-per-Tenant**: Unmaintainable at thousands of institutional tenants; connection exhaustion and massive Aurora cost.
- **Application-Level Filtering Only**: Vulnerable to regression bugs or accidental omissions by junior engineers resulting in compliance breaches.

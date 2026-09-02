# Twin AI — Architecture Reference

## Multi-Tenancy Model

Twin AI is a B2B SaaS platform. Each customer company is represented by a
**Clerk Organization**.

```
Clerk User
    └── Clerk Organization  ←── authoritative tenant boundary
            └── Twin AI resources (factories, stations, vehicles, alerts, …)
```

### Tenancy Invariant — MUST be enforced in every future phase

> **Every tenant-owned Twin AI resource must store the Clerk Organization ID.**

Examples of how this will look in future Supabase tables:

| Table | Tenant column |
|---|---|
| `factories` | `organization_id TEXT NOT NULL` |
| `stations` | `organization_id TEXT NOT NULL` |
| `vehicles` | `organization_id TEXT NOT NULL` |
| `alerts` | `organization_id TEXT NOT NULL` |
| `simulations` | `organization_id TEXT NOT NULL` |

The value stored is the Clerk organization identifier, which looks like:

```
org_xxxxxxxxxxxxxxxxxxxxxxxxxx
```

### Authorization Rule

When Supabase and RLS are introduced, every data access query **must** verify:

```sql
organization_id = <clerk_org_id_from_session>
```

**Frontend filtering alone is NEVER considered tenant isolation.**
The database-level check is mandatory.

### Where `orgId` comes from

The `orgId` is read from Clerk session claims on the server using:

```ts
const { userId, orgId, orgRole } = await auth();
```

It is **never** derived from:
- Email domain
- URL parameters
- Browser storage
- Client-submitted form values

---

## Authentication Stack

| Layer | Technology | Purpose |
|---|---|---|
| Identity | Clerk | User auth, organization, roles, sessions |
| Database (future) | Supabase | Application data, RLS enforcement |
| Rate limiting (future) | Arcjet | Abuse prevention |

---

## Organization Roles

Twin AI uses Clerk's default organization roles:

| Role | Clerk key | Intended permissions (future) |
|---|---|---|
| Company administrator | `org:admin` | Company settings, member management, factory config |
| Company member | `org:member` | View dashboards, inspect allowed resources |

Custom roles are not used in Phase 4. Role expansion will be a separate phase.

---

## Route Protection

| Route | Authentication required | Organization required | Admin required |
|---|---|---|---|
| `/` | No | No | No |
| `/sign-in` | No | No | No |
| `/sign-up` | No | No | No |
| `/organization` | Yes | No | No |
| `/app` | Yes | Yes | No |
| `/app/settings/organization` | Yes | Yes | No |
| `/app/admin-test` | Yes | Yes | Yes (`org:admin`) |

All protection is enforced **server-side** using `await auth()` in Server
Components or Route Handlers. No client-only guards are used for security
boundaries.

---

## What is NOT implemented yet

- Supabase tables
- RLS policies
- `organization_id` columns
- Factories, stations, vehicles, alerts, simulations
- Arcjet
- Dashboard
- ML / simulation
- Digital twin visualization
- Analytics

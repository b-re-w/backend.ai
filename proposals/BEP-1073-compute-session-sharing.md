---
Author: BREW (81044362+b-re-w@users.noreply.github.com)
Status: Draft
Created: 2026-10-11
Created-Version: 26.8.3
Target-Version:
Implemented-Version:
---

# Compute Session Sharing

<!-- context-for-ai
type: tech-spec
scope: Let a session owner invite users of the same project into a running interactive session (view it, open its apps) on top of the BEP-1012 RBAC data model.
key-constraints: [invitees must belong to the session's project, a share ends with the session, two share levels (app / execute), no schema change, global RBAC enforcement stays as configured]
key-decisions: [compute_session:assignment modeled as ref edge + entity-scoped permissions (BEP-1012), the generic scope-chain checker also honors entity-scoped permissions, owner / project admin / superadmin manage shares, per-user app-proxy circuits]
phases: 3
-->

## Related Issues

- JIRA: (none yet; lab fork)
- Upstream design: BEP-1012 "{Entity}:assignment" (`compute_session:assignment`), BEP-1008 entity-level scopes

## Goal

A session belongs to one user. Collaborating in the same container today means
opening an app to the public (no authentication at all) or handing out SSH keys.
BEP-1012 lists sessions among the entities that lack systematic sharing and names
`compute_session:assignment` as the mechanism. This BEP specifies that mechanism:

- The owner invites a member of the session's project; the invitee signs in with
  their own account and sees the session and opens its apps.
- The owner lists and revokes invitees at any time. Revoking also cuts the
  invitee's open app connections.
- A share is bound to that session only and ends when the session ends.

## Current design & scope, by area

### RBAC data (manager DB)

| Item | State |
|------|-------|
| Every user has a personal "user owner" role (a role with a `user`-scoped permission on that user) | ✅ exists (populated for all users) |
| `association_scopes_entities` with `auto` (ownership) and `ref` (visibility) edges | ✅ exists; vfolder invitations already migrated to `ref` edges |
| Entity-scoped permissions (`permissions.scope_type = <entity type>`) | ✅ exists; used by migrated vfolder shares |
| Generic checker (`check_permission_with_scope_chain`) honors entity-scoped permissions | ✅ exists (self-scope branch next to the AUTO scope walk) |
| Session sharing grant / revoke / list | ➕ to add |

### Session access (manager)

| Path | State |
|------|-------|
| GraphQL session node / connection: `ComputeSessionPermissionContext` supports per-object additional permissions | ✅ hook exists (`object_id_to_additional_permission_map`) |
| Session reference resolution (`resolve_session`) | ✅ owner-only; used by every session operation |
| Start app (`StartServiceAction`, a CREATE operation) | ✅ owner-only via `resolve_session`; sends the **owner's** identity to the app proxy |
| Invitee access to the above | ➕ to add, limited to read and start-app |

### App proxy (coordinator / worker)

| Item | State |
|------|-------|
| Interactive circuits carry `user_id`; the worker accepts a permit cookie only for that user | ✅ exists |
| Circuit reuse (`Circuit.find`) matches session, app and public flags, not user | ❌ an invitee would reuse the owner's circuit and fail the permit check |
| Per-user circuits for a shared session; dropping an invitee's circuits on revoke | ➕ to add |

### Clients

| Item | State |
|------|-------|
| REST v2 session sub-resource for shares, SDK, CLI | ➕ to add |
| WebUI: share dialog (owner), "shared with me" marking (invitee) | ➕ to add (separate repository) |

## Implementation design

### Data model: `compute_session:assignment`

A share of session *S* with user *U* is represented exactly as BEP-1012 describes
for vfolder sharing, so no table is added:

- a `ref` edge in `association_scopes_entities`: scope `user:U` → entity `session:S`;
- entity-scoped permissions on *U*'s user-owner role:
  `scope_type = session`, `scope_id = S`, `entity_type = session`, by share level:

| Level | Operations | Invitee can |
|-------|------------|-------------|
| `app` (default) | `read`, `create` | see the session, open its apps (start-app is a CREATE operation) |
| `execute` | `read`, `create`, `update` | also run code through the execute API and interrupt it (execute is an UPDATE operation) |

Invitees never receive `soft-delete`, `hard-delete` or `grant:*`, so they cannot
terminate, purge or reshare. RBAC operations are coarse: `update` also covers
renaming and modifying the session, so session paths open only execute/interrupt
to the `execute` level; rename/modify stay owner-only.

A share is live only while *S* is alive (not TERMINATING / TERMINATED / ERROR /
CANCELLED). Rows of ended sessions are ignored by every check and purged
(on share mutations and when the session terminates).

### Operations (REST v2)

Who may manage the shares of a session: its owner, a project admin of the
session's project (a role holding `grant:all` on `session` in that project scope,
as the system project-admin role does), and a superadmin.

| Operation | Endpoint | Contract |
|-----------|----------|----------|
| create | `POST /v2/sessions/{session_id}/shares` | body: invitee (user id or email), level (`app` / `execute`). Fails if the invitee is not a member of the session's project, is the owner, or the session is not alive. Re-sharing replaces the level. |
| search | `POST /v2/sessions/{session_id}/shares/search` | invitees of the session (user id, email, username, granted at) |
| delete | `DELETE /v2/sessions/{session_id}/shares/{user_id}` | removes the edge and the permissions, then asks the app proxy to drop the invitee's circuits for the session |

They follow the layer order: handler → adapter (`api/adapters/session_share`) →
processor/actions → service → repository (`repositories/session_share`). DTOs live
in `common/dto/manager/v2/session_share/`. SDK v2 and CLI v2 commands mirror them.

### Access by an invitee

- **Visibility.** When building `ComputeSessionPermissionContext`, the live sessions
  shared with the requester are added to `object_id_to_additional_permission_map`
  with `READ_ATTRIBUTE` and `START_APP`. Session detail and project session lists
  then include them with exactly these permissions (the WebUI hides other actions).
- **Start app.** Session resolution for `start-service` accepts a session shared
  with the requester for `create`. Every other operation keeps owner-only
  resolution. The app-proxy configuration request carries the **requester's**
  identity (user id, access key), so the circuit and its permit belong to the
  invitee.
- **Execute.** With the `execute` level, session resolution for the execute and
  interrupt APIs also accepts the shared session.
- **Check.** A repository check ("is session *S* shared with user *U* for
  operation *O*") reads the entity-scoped permissions and backs the paths above.
- **Generic checker.** `check_permission_with_scope_chain` (and its bulk form)
  already matches permissions whose scope is the target entity itself, so the
  stored shares let invitees pass `rbac_single_entity_validators` when
  enforcement is enabled; no change is needed there.

### App proxy

- Circuit reuse also matches `user_id`, so the owner and each invitee get their own
  circuit (and subdomain in wildcard mode).
- A coordinator call drops the circuits of a given user for a given session; the
  manager calls it on revoke and the app connection ends at once.

## Migration / Compatibility

- No schema change; existing sessions and APIs are untouched.
- RBAC enforcement (`manager.rbac.enforcement_enabled`) is not required and not
  changed. With enforcement on, invitees pass the same single-entity checks once
  the generic checker follows entity-scoped permissions (Open Question 1).
- App-proxy reuse now keys on user as well; for unshared sessions the owner is the
  only user, so behavior is unchanged.

## Implementation Plan

1. **Manager**: repository + service + adapter + REST v2 for shares; invitee
   visibility in the permission context; invitee start-app / execute resolution
   with the requester's identity; purge on termination. Tests per layer.
2. **App proxy**: per-user circuit reuse; drop-circuits call; manager revoke hook.
3. **Clients**: SDK v2 + CLI v2; WebUI share dialog and "shared with me" marking.

## Decision Summary

| Decision | Rationale |
|----------|-----------|
| Same-project invitees only | Matches project-level collaboration and resource policy |
| Share ends with the session | A share is an invitation into that running session, nothing else |
| `ref` edge + entity-scoped permissions, no new table | The BEP-1012 `{entity}:assignment` model; already used by migrated vfolder shares |
| Two share levels: `app` (read + create) and `execute` (+ update, used for execute/interrupt only) | Opening apps already allows running code; `execute` adds the API path for CLI/SDK users. No ownership powers (terminate, commit, reshare) |
| Owner, project admin and superadmin manage shares | BEP-1012 "Session Access Control": project admins manage access to their project's sessions |
| Shares stored as entity-scoped permissions the generic checker already reads | Invitees keep working when RBAC enforcement is enabled, without touching the checker |
| Per-user circuits | The worker binds permits to the circuit's user; sharing must not weaken that check |

## Open Questions

- None.

## References

- BEP-1012 Backend.AI RBAC Feature Specification (`{Entity}:assignment`, VFolder Sharing)
- BEP-1008 RBAC (entity-level scopes, `ref` relations)
- BEP-1005 Unified App Proxy

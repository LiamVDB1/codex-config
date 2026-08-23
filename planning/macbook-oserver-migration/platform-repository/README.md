# Homeserver Platform Repository

This directory is the canonical source subtree for the two-host platform. The Git remote and approved commit are declared in `repository.json`; host paths are durable deployment clones, never source authority.

Every service record must pass `scripts/platform_contracts.py service`. The validator requires source SHA, per-architecture digests, health, resource, backup and rollback authority and rejects unknown fields, dirty source, floating tags, non-loopback bindings and literal secret fields.

BUILD-001 permits only synthetic loopback deployment. Public routing, production replacement and stateful migration remain forbidden until their later BUILD boundaries.

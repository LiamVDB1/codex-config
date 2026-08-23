# Synthetic deployment proof

`SVC-SYNTHETIC` is the non-stateful BUILD-001 canary. It has no secrets or durable mounts and may bind only `127.0.0.1:18180` on either host.

`deployment.py` rejects dirty source, the wrong source commit, the wrong host architecture, unknown image digests and incomplete approval metadata before emitting a hardened `docker run` plan. Images are built natively on each host from the same approved source commit and retained by immutable local image ID for rollback.

The final `approval.json` is generated only after both architecture-specific v1 and v2 image IDs are known. Its artifact-index digest binds the per-host IDs without claiming a registry manifest list.

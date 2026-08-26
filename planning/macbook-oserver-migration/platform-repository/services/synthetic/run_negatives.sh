#!/usr/bin/env bash
# Deterministic mandatory-negative runner for the synthetic rollout.
# Usage: run_negatives.sh <clone> <bundle-dir> <out-dir> <amd64-digest> <arm64-digest>
set -u
C="$1"; B="$2"; N="$3"; AMD="$4"; ARM="$5"
S="$C/planning/macbook-oserver-migration/platform-repository/services/synthetic"
R="python3 $S/host_rollout.py"
mkdir -p "$N" /tmp/negdir-work

echo "[neg1] dirty source"
touch "$C/planning/macbook-oserver-migration/platform-repository/services/synthetic/dirt.txt"
"$R" plan --approval "$B/approval.json" --clone "$C" --host homeserver \
  --architecture linux/amd64 --image-digest "$AMD" --action deploy \
  --out-dir /tmp/negdir-work >"$N/dirty-source.txt" 2>&1 || true
git -C "$C" clean -qfd planning/ ; git -C "$C" checkout -q -- .
grep -q "not clean" "$N/dirty-source.txt" || echo "UNEXPECTED: dirty-source not rejected"

echo "[neg2] forged provenance receipt vs live clone"
FORGED=$(mktemp -d)
python3 - "$B" "$S" "$C" "$AMD" "$N" <<'PY'
import json, sys
from pathlib import Path
bundle, sdir, clone, amd, out = sys.argv[1:6]
sys.path.insert(0, sdir)
from deployment import build_runtime_plan, DeploymentError
approval = json.load(open(Path(bundle) / "approval.json"))
forged = json.load(open(Path(bundle) / "provenance-homeserver.json"))
forged["subdir_tree"] = "0" * 40
try:
    build_runtime_plan(approval, host="homeserver", architecture="linux/amd64",
        provenance=forged, image_digest=amd, action="deploy", verify_clone=Path(clone))
    print("NOT REJECTED")
except DeploymentError as exc:
    print(f"FAIL: {exc}")
PY
grep -q "does not match the live clone" "$N/forged-provenance.txt" 2>/dev/null || python3 - "$B" "$S" "$C" "$AMD" > "$N/forged-provenance.txt" 2>&1 <<'PY' || true
import json, sys
from pathlib import Path
bundle, sdir, clone, amd = sys.argv[1:5]
sys.path.insert(0, sdir)
from deployment import build_runtime_plan, DeploymentError
approval = json.load(open(Path(bundle) / "approval.json"))
forged = json.load(open(Path(bundle) / "provenance-homeserver.json"))
forged["subdir_tree"] = "0" * 40
try:
    build_runtime_plan(approval, host="homeserver", architecture="linux/amd64",
        provenance=forged, image_digest=amd, action="deploy", verify_clone=Path(clone))
    print("NOT REJECTED")
except DeploymentError as exc:
    print(f"FAIL: {exc}")
PY
grep -q "does not match the live clone" "$N/forged-provenance.txt" && echo "[neg2] rejected" || echo "UNEXPECTED: forged-provenance accepted"

echo "[neg3] wrong approved commit"
mkdir -p /tmp/neg-badbundle
python3 - "$B" <<'PY'
import json, hashlib, sys
from pathlib import Path
b = Path(sys.argv[1])
idx = json.loads((b / "artifact-index.json").read_text())
idx["source_commit_sha"] = "e" * 40
raw = (json.dumps(idx, indent=2, sort_keys=True) + "
").encode()
(b2 := Path("/tmp/neg-badbundle")).mkdir(exist_ok=True)
(b2 / "artifact-index.json").write_bytes(raw)
a = dict(idx); a["schema_version"] = "homeserver-synthetic-approval/v1"
a["artifact_index_digest"] = "sha256:" + hashlib.sha256(raw).hexdigest()
(b2 / "approval.json").write_text(json.dumps(a, indent=2))
PY
"$R" plan --approval /tmp/neg-badbundle/approval.json --clone "$C" --host homeserver \
  --architecture linux/amd64 --image-digest "$AMD" --action deploy \
  --out-dir /tmp/negdir-work >"$N/wrong-commit.txt" 2>&1 || true
grep -q "does not match approved commit eee" "$N/wrong-commit.txt" || echo "UNEXPECTED: wrong-commit not rejected"

echo "[neg4] unapproved digest"
"$R" plan --approval "$B/approval.json" --clone "$C" --host homeserver \
  --architecture linux/amd64 --image-digest sha256:$(printf '0%.0s' {1..64}) --action deploy \
  --out-dir /tmp/negdir-work >"$N/unapproved-digest.txt" 2>&1 || true
grep -q "is not approved" "$N/unapproved-digest.txt" || echo "UNEXPECTED: unapproved-digest not rejected"

echo "[neg5] architecture swap"
"$R" plan --approval "$B/approval.json" --clone "$C" --host homeserver \
  --architecture linux/arm64 --image-digest "$ARM" --action deploy \
  --out-dir /tmp/negdir-work >"$N/arch-swap.txt" 2>&1 || true
grep -qE "not approved for|is not approved" "$N/arch-swap.txt" || echo "UNEXPECTED: arch-swap not rejected"

echo "[neg6] rollback digest on deploy action"
"$R" plan --approval "$B/approval.json" --clone "$C" --host homeserver \
  --architecture linux/amd64 --image-digest sha256:83798683c1c4af2023438e53dd29cb5acf809dc8d4f3c3fe8d9c89cda73c4618 \
  --action deploy --out-dir /tmp/negdir-work >"$N/rollback-as-deploy.txt" 2>&1 || true
grep -q "is not approved" "$N/rollback-as-deploy.txt" || echo "UNEXPECTED: rollback-as-deploy not rejected"

echo "== negatives complete =="

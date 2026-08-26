#!/usr/bin/env bash
# Deterministic mandatory-negative runner for the synthetic rollout.
# Usage: run_negatives.sh <clone> <bundle-dir> <out-dir> <amd64-digest> <arm64-digest>
set -u
CLONE="$1"
BUNDLE="$2"
OUT="$3"
AMD="$4"

REPO_DIR="$CLONE/planning/macbook-oserver-migration/platform-repository"
SYNTH="$REPO_DIR/services/synthetic"
ROLLOUT="$SYNTH/host_rollout.py"
mkdir -p "$OUT" "$(mktemp -u)"

fail() { echo "UNEXPECTED($1): see $2"; }

echo "[neg1] dirty source"
touch "$SYNTH/dirt.txt"
python3 "$ROLLOUT" plan --approval "$BUNDLE/approval.json" --clone "$CLONE" \
  --host homeserver --architecture linux/amd64 --image-digest "$AMD" \
  --action deploy --out-dir "$OUT/negwork" >"$OUT/dirty-source.txt" 2>&1 || true
git -C "$CLONE" clean -qfd planning/
git -C "$CLONE" checkout -q -- .
grep -q "not clean" "$OUT/dirty-source.txt" \
  || fail neg1 "$OUT/dirty-source.txt"

echo "[neg2] forged provenance receipt vs live clone"
cat > "$OUT/forged_neg.py" <<FORGE
import json, sys
from pathlib import Path
sys.path.insert(0, "$SYNTH")
from deployment import build_runtime_plan, DeploymentError
approval = json.load(open("$BUNDLE/approval.json"))
forged = json.load(open("$BUNDLE/provenance-homeserver.json"))
forged["subdir_tree"] = "0" * 40
try:
    build_runtime_plan(approval, host="homeserver", architecture="linux/amd64",
        provenance=forged, image_digest="$AMD", action="deploy",
        verify_clone=Path("$CLONE"))
    print("NOT REJECTED")
except DeploymentError as exc:
    print("FAIL:", exc)
FORGE
python3 "$OUT/forged_neg.py" >"$OUT/forged-provenance.txt" 2>&1 || true
grep -q "does not match the live clone" "$OUT/forged-provenance.txt" \
  || fail neg2 "$OUT/forged-provenance.txt"

echo "[neg3] wrong approved commit"
mkdir -p /tmp/neg-badbundle
BADIDX=$(mktemp)
python3 - "$BUNDLE" "$BADIDX" <<PYGEN
import hashlib, json, sys
from pathlib import Path
idx = json.loads((Path(sys.argv[1]) / "artifact-index.json").read_text())
idx["source_commit_sha"] = "e" * 40
raw = (json.dumps(idx, indent=2, sort_keys=True) + chr(10)).encode()
Path(sys.argv[2]).write_bytes(raw)
approval = dict(idx)
approval["schema_version"] = "homeserver-synthetic-approval/v1"
approval["artifact_index_digest"] = "sha256:" + hashlib.sha256(raw).hexdigest()
Path("/tmp/neg-badbundle/approval.json").write_text(json.dumps(approval, indent=2))
import shutil
shutil.copyfile(Path(sys.argv[1]) / "artifact-index.json",
                "/tmp/neg-badbundle/artifact-index-original.json")
PYGEN
cp "$BUNDLE/artifact-index.json" /tmp/neg-badbundle/artifact-index.json
mv "$BUNDLE/approval.json" "$BUNDLE/approval.json.keep"
cp /tmp/neg-badbundle/approval.json "$BUNDLE/approval.json"
python3 "$ROLLOUT" plan --approval "$BUNDLE/approval.json" --clone "$CLONE" \
  --host homeserver --architecture linux/amd64 --image-digest "$AMD" \
  --action deploy --out-dir "$OUT/negwork" >"$OUT/wrong-commit.txt" 2>&1 || true
mv "$BUNDLE/approval.json.keep" "$BUNDLE/approval.json"
rm -f /tmp/neg-badbundle/artifact-index-original.json
grep -q "does not match approved commit eee" "$OUT/wrong-commit.txt" \
  || fail neg3 "$OUT/wrong-commit.txt"

echo "[neg4] unapproved digest"
ZERODIGEST="sha256:0000000000000000000000000000000000000000000000000000000000000000"
python3 "$ROLLOUT" plan --approval "$BUNDLE/approval.json" --clone "$CLONE" \
  --host homeserver --architecture linux/amd64 --image-digest "$ZERODIGEST" \
  --action deploy --out-dir "$OUT/negwork" >"$OUT/unapproved-digest.txt" 2>&1 || true
grep -q "is not approved" "$OUT/unapproved-digest.txt" \
  || fail neg4 "$OUT/unapproved-digest.txt"

echo "[neg5] architecture swap"
ARM="$5"
python3 "$ROLLOUT" plan --approval "$BUNDLE/approval.json" --clone "$CLONE" \
  --host homeserver --architecture linux/arm64 --image-digest "$ARM" \
  --action deploy --out-dir "$OUT/negwork" >"$OUT/arch-swap.txt" 2>&1 || true
grep -qE "not approved for|is not approved" "$OUT/arch-swap.txt" \
  || fail neg5 "$OUT/arch-swap.txt"

echo "[neg6] rollback digest on deploy action"
ROLLBACK_AMD="sha256:83798683c1c4af2023438e53dd29cb5acf809dc8d4f3c3fe8d9c89cda73c4618"
python3 "$ROLLOUT" plan --approval "$BUNDLE/approval.json" --clone "$CLONE" \
  --host homeserver --architecture linux/amd64 --image-digest "$ROLLBACK_AMD" \
  --action deploy --out-dir "$OUT/negwork" >"$OUT/rollback-as-deploy.txt" 2>&1 || true
grep -q "is not approved" "$OUT/rollback-as-deploy.txt" \
  || fail neg6 "$OUT/rollback-as-deploy.txt"

echo "== negatives complete =="

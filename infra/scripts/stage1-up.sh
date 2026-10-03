#!/usr/bin/env bash
# Phase 0, Stage 1: init -> validate -> plan -> (you confirm) -> apply -> kubeconfig check.
#   export VULTR_API_KEY=...        (use TF=tofu if you use OpenTofu)
set -euo pipefail
TF=${TF:-terraform}
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE/../vultr/stage1"

: "${VULTR_API_KEY:?export VULTR_API_KEY first}"
command -v "$TF" >/dev/null || { echo "$TF not found (try TF=tofu)"; exit 1; }
[ -f terraform.tfvars ] || { echo "create terraform.tfvars from terraform.tfvars.example first"; exit 1; }

$TF init -input=false
$TF validate
$TF plan -input=false -out=tfplan

read -r -p "Apply this plan? This creates billable Vultr resources. [y/N] " ans
[ "$ans" = "y" ] || { rm -f tfplan; echo "aborted"; exit 0; }

$TF apply -input=false tfplan
rm -f tfplan

echo
"$HERE/kubeconfig.sh"

echo
echo "== Stage 1 outputs"
$TF output
echo
echo "Registry credentials (sensitive; do NOT paste into the repo):"
echo "  $TF -chdir=$(pwd) output -json registry_root_user | jq"

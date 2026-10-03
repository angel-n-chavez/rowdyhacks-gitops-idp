#!/usr/bin/env bash
# Look up values you need for terraform.tfvars.
#   export VULTR_API_KEY=...
#   scripts/vultr-lookups.sh versions   # VKE Kubernetes versions (paste one into k8s_version)
#   scripts/vultr-lookups.sh os         # exact OS names (for os_name)
set -euo pipefail
: "${VULTR_API_KEY:?export VULTR_API_KEY first}"
api() { curl -fsS -H "Authorization: Bearer $VULTR_API_KEY" "https://api.vultr.com/v2/$1"; }
case "${1:-}" in
  versions) api kubernetes/versions | jq -r '.versions[]' ;;
  os)       api "os?per_page=500" | jq -r '.os[] | select(.family=="debian" or .family=="ubuntu") | .name' ;;
  *) echo "usage: $0 versions|os" >&2; exit 2 ;;
esac

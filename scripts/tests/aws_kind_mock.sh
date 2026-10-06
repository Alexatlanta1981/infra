#!/usr/bin/env bash
set -euo pipefail
case "$1 $2" in
  "sts get-caller-identity")
    printf '%s\n' "000000000000"
    ;;
  "eks update-kubeconfig")
    test "$(kubectl config current-context)" = "$EXPECTED_KIND_CONTEXT"
    ;;
  *)
    echo "Unexpected AWS command in kind smoke test: $1 $2" >&2
    exit 1
    ;;
esac

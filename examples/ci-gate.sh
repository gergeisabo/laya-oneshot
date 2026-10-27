#!/bin/sh
# Fail a build when the change description does not clearly read as safe.
#   exit 0 = confident   exit 1 = not confident enough   exit 2 = could not decide
set -eu

DESCRIPTION=$(git log -1 --pretty=%B)

laya-oneshot --ask "Is this change clearly a documentation-only edit?" \
             --threshold 0.85 \
             "$DESCRIPTION" > /tmp/laya-gate.out || status=$?

cat /tmp/laya-gate.out
case "${status:-0}" in
  0) echo "gate: pass" ;;
  1) echo "gate: needs a human" >&2; exit 1 ;;
  *) echo "gate: could not decide" >&2; exit 2 ;;
esac

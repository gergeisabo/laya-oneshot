#!/bin/sh
# Triage a maildir of plain-text mails, keep the ones that need a reply.
set -eu
for mail in "$1"/*.txt; do
  if laya-oneshot --preset email --threshold 0.7 -- "$(cat "$mail")" > /dev/null; then
    echo "$mail"
  fi
done

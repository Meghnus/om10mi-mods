#!/bin/bash
# Builds the version 56 card file (macOS: double-click this file).
cd "$(dirname "$0")" || exit 1

PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    PY="$c"
    break
  fi
done

if [ -z "$PY" ]; then
  echo
  echo "Python 3.10 or newer was not found."
  echo "Install it from https://www.python.org/downloads/ (or: brew install python), then run this file again."
  echo
  read -r -p "Press Enter to close ..." _
  exit 1
fi

"$PY" om10mi.py build --ask-sd
rc=$?

if [ "$rc" -eq 0 ] && [ -d out ]; then
  echo
  echo "Output folder: $(pwd)/out"
  open out >/dev/null 2>&1
fi
echo
read -r -p "Press Enter to close ..." _
exit "$rc"

#!/bin/sh
# Builds the version 56 card file (Linux: ./om10mi-build.sh).
cd "$(dirname "$0")" || exit 1

PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    PY="$c"
    break
  fi
done

if [ -z "$PY" ]; then
  echo "Python 3.10 or newer was not found."
  echo "Install it with your package manager (for example: sudo apt install python3) and run this again."
  exit 1
fi

"$PY" om10mi.py build --ask-sd
rc=$?

if [ "$rc" -eq 0 ] && [ -d out ]; then
  echo
  echo "Output folder: $(pwd)/out"
  if command -v xdg-open >/dev/null 2>&1 && [ -n "$DISPLAY$WAYLAND_DISPLAY" ]; then
    xdg-open out >/dev/null 2>&1 &
  fi
fi
exit "$rc"

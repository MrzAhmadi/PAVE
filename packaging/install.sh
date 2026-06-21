#!/bin/bash
set -e

WHEEL=$(ls pave*.whl 2>/dev/null | head -1)
if [ -z "$WHEEL" ]; then
  echo "ERROR: no wheel file found in current directory." >&2
  exit 1
fi

echo "Installing PAVE from ${WHEEL} ..."
python3 -m venv /opt/pave
/opt/pave/bin/pip install --quiet --upgrade pip
/opt/pave/bin/pip install --quiet "${WHEEL}"
ln -sf /opt/pave/bin/pave /usr/local/bin/pave

echo "Done. Run: pave --help"

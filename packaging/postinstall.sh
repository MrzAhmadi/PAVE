#!/bin/sh
set -e
python3 -m venv /opt/pave
/opt/pave/bin/pip install --quiet --upgrade pip
/opt/pave/bin/pip install --quiet /usr/lib/pave/*.whl
echo "pave installed — run: pave --help"

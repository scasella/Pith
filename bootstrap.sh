#!/usr/bin/env bash
# bootstrap.sh — toolchain for the seed. Linux x64 and macOS (arm64/x64). Writes .env; `source .env` afterwards.
set -euo pipefail
OS="$(uname -s)"; ARCH="$(uname -m)"
mkdir -p .tools && cd .tools
# fail on HTTP errors and retry transient ones, so a bad download is never mistaken for a tool
fetch() { curl -fsSL --retry 5 --retry-delay 3 --retry-all-errors -o "$1" "$2"; }
get_dafny() { fetch dafny.zip "https://github.com/dafny-lang/dafny/releases/download/v4.11.0/$1" && unzip -qo dafny.zip && rm dafny.zip; }  # &&: set -e is off inside a function called from ||
if [ "$OS" = "Darwin" ]; then
  if command -v dafny >/dev/null; then DAFNY_BIN="$(command -v dafny)"; echo "using $(dafny --version) from PATH (brew install dafny)";
  else
    case "$ARCH" in arm64) Z=dafny-4.11.0-arm64-osx-13.0.zip ;; *) Z=dafny-4.11.0-x64-osx-13.0.zip ;; esac
    [ -x dafny/dafny ] || get_dafny "$Z"
    DAFNY_BIN="$PWD/dafny/dafny"
  fi
  command -v java >/dev/null || echo "java not found: brew install openjdk, then add /opt/homebrew/opt/openjdk/bin to PATH (TLC needs it)"
else
  [ -x dafny/dafny ] || get_dafny dafny-4.11.0-x64-ubuntu-22.04.zip
  DAFNY_BIN="$PWD/dafny/dafny"
  command -v java >/dev/null || echo "java not found: install a JRE (TLC needs it)"
fi
[ -f tla2tools.jar ] || fetch tla2tools.jar https://github.com/tlaplus/tlaplus/releases/latest/download/tla2tools.jar
[ -x "$DAFNY_BIN" ] || { echo "dafny not found at $DAFNY_BIN after download" >&2; exit 1; }
cd ..
# one interpreter, one architecture: a venv avoids mixed arm64/x86_64 wheels in a shared site-packages
python3 -m venv .venv && . .venv/bin/activate
python3 -m pip install -q --upgrade pip
python3 -m pip install -q DafnyRuntimePython==4.11.0 hypothesis pytest pyyaml jsonschema cryptography playwright
[ -n "${SEED_CHROMIUM:-}" ] || python3 -m playwright install chromium >/dev/null 2>&1 || echo "playwright chromium install failed: set SEED_CHROMIUM to an existing binary"
printf 'source %s/.venv/bin/activate\nexport DAFNY=%s\nexport TLA2TOOLS=%s/.tools/tla2tools.jar\n' "$PWD" "$DAFNY_BIN" "$PWD" > .env
echo "ok: source .env && python3 gate/app_gate.py --out ../evidence-001"

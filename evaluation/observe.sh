#!/usr/bin/env bash
# Compiles the corpus and the observer, then records reference observations
# for every pair in evaluation/pairs.txt into evaluation/observations/.
# Run from anywhere:  bash evaluation/observe.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="$(mktemp -d)"
trap 'rm -rf "$BUILD"' EXIT

javac -parameters -d "$BUILD" \
  "$ROOT"/cases/jpamb/utils/*.java \
  "$ROOT"/cases/jpamb/cases/Refactorings.java \
  "$ROOT"/evaluation/observe/Observe.java

# -ea enables assertions, so `assert` statements can fail as they do in JPAMB.
java -ea -cp "$BUILD" Observe "$ROOT/evaluation/pairs.txt" "$ROOT/evaluation/observations"

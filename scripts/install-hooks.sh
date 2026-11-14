#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
if ! git rev-parse --git-dir >/dev/null 2>&1; then
  printf 'PIA: pacote sem Git; hook de desenvolvimento não aplicável.\n'
  exit 0
fi
hook="$(git rev-parse --git-path hooks/pre-commit)"
mkdir -p -- "$(dirname -- "$hook")"
if [[ -f "$hook" ]] && ! cmp -s scripts/pre-commit "$hook"; then
  printf 'PIA: hook pre-commit existente preservado; integre scripts/pre-commit antes de commitar.\n' >&2
  exit 1
fi
cp scripts/pre-commit "$hook"
chmod +x "$hook"
printf 'PIA: hook pre-commit instalado.\n'

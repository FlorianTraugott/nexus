#!/usr/bin/env bash
# Fetch the public-domain NIST eval corpus (17 U.S.C. sec. 105).
# The synthetic fixture (ocr_test_document.pdf) is committed, not fetched.
# Portable to macOS bash 3.2 (no associative arrays).
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/corpus"
mkdir -p "$DIR"

NAMES=(
  "NIST.CSWP.29.pdf"
  "NIST.IR.8286r1.pdf"
  "NIST.SP.1299.pdf"
  "NIST.SP.1300.pdf"
  "NIST.SP.1301.pdf"
)
URLS=(
  "https://nvlpubs.nist.gov/nistpubs/CSWP/NIST.CSWP.29.pdf"
  "https://nvlpubs.nist.gov/nistpubs/ir/2025/NIST.IR.8286r1.pdf"
  "https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.1299.pdf"
  "https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.1300.pdf"
  "https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.1301.pdf"
)

for i in "${!NAMES[@]}"; do
  name="${NAMES[$i]}"
  url="${URLS[$i]}"
  dest="$DIR/$name"
  if [[ -f "$dest" ]]; then
    echo "  skip (exists): $name"
    continue
  fi
  echo "  fetching: $name"
  curl -fSL --retry 3 -o "$dest" "$url"
  if [[ "$(file -b --mime-type "$dest")" != "application/pdf" ]]; then
    echo "ERROR: $name is not a PDF - bad URL? Removing." >&2
    rm -f "$dest"
    exit 1
  fi
done

echo "Corpus ready in $DIR"
ls -la "$DIR"/*.pdf

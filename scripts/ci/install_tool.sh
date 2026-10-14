#!/usr/bin/env bash
# Download a pinned static binary into ./bin. usage: install_tool.sh actionlint|gitleaks VERSION
set -euo pipefail
tool=$1 ver=$2
mkdir -p bin
case "$tool" in
  actionlint) url="https://github.com/rhysd/actionlint/releases/download/v${ver}/actionlint_${ver}_linux_amd64.tar.gz" ;;
  gitleaks) url="https://github.com/gitleaks/gitleaks/releases/download/v${ver}/gitleaks_${ver}_linux_x64.tar.gz" ;;
  *) echo "unknown tool: $tool" >&2; exit 2 ;;
esac
curl -fsSL "$url" | tar -xz -C bin "$tool"
"./bin/$tool" --version

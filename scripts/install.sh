#!/usr/bin/env bash
# Installs system packages (if missing) and prepares .env. Ollama itself is installed separately.
set -euo pipefail
cd "$(dirname "$0")/.."
sudo apt update
sudo apt install -y python3 passwd coreutils libc-bin util-linux curl
[ -f .env ] || { cp .env.example .env; chmod 600 .env; echo "Created .env"; }
echo "If Ollama is missing:  curl -fsSL https://ollama.com/install.sh | sh   then   ollama pull llama3.2:3b"
python3 agent23.py --check || echo "(--check reported issues above; fix them, then rerun)"

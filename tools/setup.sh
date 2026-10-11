#!/usr/bin/env bash
set -euo pipefail
repo_root=$(cd "$(dirname "$0")/.." && pwd)
tool_root=/workspace/tooling/sjasmplus
assembler_commit=7dbf9394d9357073269dc55c55036a16cc16cb90
if [ ! -d "$tool_root" ]; then
    mkdir -p /workspace/tooling
    git clone https://github.com/z00m128/sjasmplus.git "$tool_root"
    git -C "$tool_root" checkout --detach "$assembler_commit"
fi
test "$(git -C "$tool_root" rev-parse HEAD)" = "$assembler_commit"
git -C "$tool_root" diff --quiet
make -C "$tool_root" -j2 USE_LUA=0
cd "$repo_root"
if [ ! -x .venv/bin/python ]; then
    python3 -m venv .venv
fi
.venv/bin/python -m pip install --disable-pip-version-check -r requirements-dev.txt
make test PYTHON="$repo_root/.venv/bin/python" SJASMPLUS="$tool_root/sjasmplus"

#!/usr/bin/env bash
# Установка gstack в .claude/skills проекта (нужен Bun >= 1.3.3).
set -e
cd "$(dirname "$0")/skills"
[ -d gstack ] || git clone --single-branch --depth 1 https://github.com/garrytan/gstack.git gstack
cd gstack && ./setup --host claude

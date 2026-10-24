#!/bin/bash
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )"
cd "$DIR"
mkdir -p logs
exec .venv/bin/python pia_launcher.py >> logs/launcher.log 2>&1

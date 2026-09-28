#!/usr/bin/env bash
set -o errexit

if [ -f requirements.txt ]; then
  pip install -r requirements.txt
elif [ -f backend/requirements.txt ]; then
  pip install -r backend/requirements.txt
elif [ -f ../requirements.txt ]; then
  pip install -r ../requirements.txt
fi

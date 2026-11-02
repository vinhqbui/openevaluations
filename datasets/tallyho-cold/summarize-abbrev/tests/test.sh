#!/bin/bash
# Copies the hidden test in and runs the whole suite; reward 1 when everything passes.
mkdir -p /logs/verifier
cp /tests/test_summarize_hidden.py /app/tests/test_summarize_hidden.py
cd /app && python -m pytest -q -p no:cacheprovider tests
status=$?
if [ "$status" -eq 0 ]; then echo 1 > /logs/verifier/reward.txt; else echo 0 > /logs/verifier/reward.txt; fi
exit 0

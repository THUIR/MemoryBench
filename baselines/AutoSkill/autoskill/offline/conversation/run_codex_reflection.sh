#!/usr/bin/env bash

set -euo pipefail

INPUT_JSON="${1:?missing input_json}"
OUTPUT_JSON="${2:?missing output_json}"
MAX_RETRIES="${3:-}"

if [[ -n "${MAX_RETRIES}" ]]; then
  python -m autoskill.offline.conversation.run_codex_reflection --max-retries "${MAX_RETRIES}" "${INPUT_JSON}" "${OUTPUT_JSON}"
else
  python -m autoskill.offline.conversation.run_codex_reflection "${INPUT_JSON}" "${OUTPUT_JSON}"
fi

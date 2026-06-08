export DASHSCOPE_API_KEY=""

python -m autoskill.offline.conversation.self_evolve.orchestrator \
  --train-root data/train \
  --train-meta-info-jsonl data/train/meta_info.jsonl \
  --eval-root data/eval \
  --eval-meta-info-jsonl data/eval/meta_info.jsonl \
  --run-name Reflection \
  --extract-mode common \
  --eval-before 1 \
  --eval-after 1 \
  --resume 1 \
  --session-stamp 2026-0427-1253 \
  --reflection-mode codex \
  --codex-auto-backend llm \
  --codex-reflection-max-retries 3 \
  --max-rounds 6 \
  --max-candidate-prompt-change-ratio 0.3 \
  --base-prompt-min-length-ratio 0.7 \
  --base-prompt-max-length-ratio 2.5 \
  --max-workers 16 \
  --auto-promote 1 \
  --disable-env-proxy 1 \
  --llm-provider codex \
  --llm-model gpt-5.4-mini \
  --embeddings-provider dashscope \
  --max-failed-retries 5

#!/usr/bin/env bash
set -e
pip install garak
export OPENAI_API_KEY=ollama
# scan the raw model
python -m garak \
  --model_type openai.OpenAICompatible \
  --model_name qwen2.5:3b \
  --generations 1 \
  --probes dan,promptinject \
  --report_prefix garak_runs/raw_model
echo "Raw-model garak report written to garak_runs/. Compare against the guarded /chat endpoint to show the guardrails effect."

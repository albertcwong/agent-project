#!/bin/bash
# Run evals for models with 60s delay between runs for rate limiting.

set -e
cd "$(dirname "$0")/.."

run_model() {
  local model=$1
  local provider=${2:-salesforce}
  echo ""
  echo "=== $model (provider: $provider) ==="
  uv run python evaluation/run_eval.py --model "$model" --provider "$provider"
}

# Queue: gemini-2.5-pro, claude-opus-4-6-v1 (salesforce), gpt-5.4 (openai)
run_model "gemini-2.5-pro" "salesforce"
echo "Waiting 60s for rate limit..."
sleep 60

run_model "claude-opus-4-6-v1" "salesforce"
echo "Waiting 60s for rate limit..."
sleep 60

run_model "gpt-5.4" "openai"
echo ""
echo "=== All 3 model evals complete ==="

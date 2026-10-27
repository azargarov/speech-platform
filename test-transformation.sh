#!/usr/bin/env bash
set -uo pipefail

cd "$(dirname "$0")"

include_cloud=0
if [[ $# -gt 1 || ( $# -eq 1 && "$1" != "--allow-cloud" ) ]]; then
    echo "usage: $0 [--allow-cloud]" >&2
    exit 2
fi
if [[ $# -eq 1 ]]; then
    include_cloud=1
fi

PYTHON=".venv/bin/python"
OUT="samples/out/manual-transformations-$(date +%Y%m%d-%H%M%S)"

MODELS=(local-qwen)
if [[ "$include_cloud" -eq 1 ]]; then
    MODELS+=(groq-qwen groq-gpt-oss)
fi
MODES=(written polite diplomatic)

mkdir -p "$OUT"
chmod 700 "$OUT"

passed=0
failed=0

for file in samples/text/{en,sv,ru}-{informal,polite,rude}.txt; do
    [[ -f "$file" ]] || { echo "Missing: $file"; exit 1; }

    language=$(basename "$file" | cut -d- -f1)

    for mode in "${MODES[@]}"; do
        for model in "${MODELS[@]}"; do
            name="$(basename "$file" .txt)-${mode}-${model}"

            args=()
            if [[ "$model" == groq-* ]]; then
                args+=(--allow-cloud)
            fi

            echo
            echo "=================================================="
            echo "File: $file"
            echo "Mode: $mode"
            echo "Model: $model"
            echo "=================================================="
            cat "$file"
            echo "--------------------------------------------------"
            if "$PYTHON" -m scripts.qualify transform \
                --text-file "$file" \
                --mode "$mode" \
                --format normal \
                --target-language none \
                --model "$model" \
                "${args[@]}" \
                --report "$OUT/$name-report.json" \
                --evidence "$OUT/$name-evidence.json"; then
                ((passed+=1))
            else
                ((failed+=1))
            fi
        done
    done
done

echo
echo "=================================================="
echo "COMPLETED"
echo "Passed: $passed"
echo "Failed: $failed"
if [[ "$include_cloud" -eq 1 ]]; then
    echo "Cloud models: included by explicit --allow-cloud"
else
    echo "Cloud models: skipped (pass --allow-cloud to include them)"
fi
echo "Reports: $OUT"
echo "=================================================="

[[ "$failed" -eq 0 ]]

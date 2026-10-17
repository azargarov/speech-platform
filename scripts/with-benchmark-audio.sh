#!/usr/bin/env bash
set -euo pipefail

if (($# == 0)); then
  echo 'usage: [SPEECH_BENCHMARK_AUDIO=path] with-benchmark-audio.sh command [args...]' >&2
  exit 2
fi

benchmark_audio="${SPEECH_BENCHMARK_AUDIO:-private/audio/russian.m4a}"
if [[ ! -f "$benchmark_audio" ]]; then
  echo "benchmark audio file not found: $benchmark_audio" >&2
  exit 1
fi
export SPEECH_BENCHMARK_AUDIO="$benchmark_audio"
exec "$@"

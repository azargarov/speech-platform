#!/usr/bin/env bash
set -euo pipefail
set -o noclobber

usage='usage: M00_BENCHMARK_SOURCE=/path/to/local/benchmark scripts/archive-m00.sh /path/to/new/archive.tar\n   or: scripts/archive-m00.sh /path/to/local/benchmark /path/to/new/archive.tar'

if (($# == 2)); then
  source_directory="$1"
  archive_destination="$2"
elif (($# == 1)) && [[ -n "${M00_BENCHMARK_SOURCE:-}" ]]; then
  source_directory="$M00_BENCHMARK_SOURCE"
  archive_destination="$1"
else
  printf '%b\n' "$usage" >&2
  exit 2
fi

if [[ ! -d "$source_directory" ]]; then
  echo 'Benchmark source directory does not exist' >&2
  exit 1
fi
if [[ -e "$archive_destination" || -L "$archive_destination" ]]; then
  echo 'Refusing to overwrite existing archive' >&2
  exit 1
fi
source_directory="$(realpath "$source_directory")"
archive_destination="$(realpath -m "$archive_destination")"
archive_complete=false
cleanup() {
  if [[ "$archive_complete" != true ]]; then
    rm -f -- "$archive_destination"
  fi
}
trap cleanup EXIT

find "$source_directory" -type f -print0 |
  while IFS= read -r -d "" source_file; do
    filename="${source_file##*/}"
    case "$filename" in
      *.py|*.sh|*.yaml|*.yml|Dockerfile*|requirements*.txt|*.md)
        printf '%s\0' "${source_file#"$source_directory"/}"
        ;;
    esac
  done |
tar --directory="$source_directory" --create --file="$archive_destination" --null --files-from=- --keep-old-files
archive_complete=true

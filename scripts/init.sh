#!/bin/sh
set -eu

fail() {
    printf 'make init: %s\n' "$1" >&2
    exit 1
}

require_tools() {
    for tool do
        command -v "$tool" >/dev/null 2>&1 || fail "required system tool '$tool' is unavailable"
    done
}

ensure_private_dir() {
    directory=$1
    [ ! -L "$directory" ] || fail "refusing symlinked private directory: $directory"
    if [ -e "$directory" ]; then
        [ -d "$directory" ] || fail "private path is not a directory: $directory"
    else
        if ! mkdir -m 700 "$directory" 2>/dev/null; then
            # Another concurrent `make init` may have created it after our check.
            [ -d "$directory" ] && [ ! -L "$directory" ] || fail "could not create private directory: $directory"
        fi
    fi
    chmod 700 "$directory" || fail "could not secure private directory: $directory"
}

umask 077
require_tools mkdir chmod

if [ -L .env ]; then
    fail "refusing symlinked .env; preserve it and inspect it manually"
fi

if [ -e .env ]; then
    [ -f .env ] || fail ".env exists but is not a regular file; leaving it untouched"
    ensure_private_dir private
    ensure_private_dir private/audio
    ensure_private_dir private/deployment
    printf '%s\n' 'Existing .env preserved; no token or configuration was changed.'
    printf '%s\n' 'Run make preflight PYTHON=.venv/bin/python to validate the existing setup.'
    exit 0
fi

require_tools openssl mktemp ln rm
[ -f .env.example ] && [ ! -L .env.example ] || fail '.env.example is missing or not a regular file'

validate_template_token_line() {
    candidate=$1
    tab=$(printf '\t')
    while :; do
        case "$candidate" in
            ' '*) candidate=${candidate#?} ;;
            "$tab"*) candidate=${candidate#?} ;;
            *) break ;;
        esac
    done

    case "$candidate" in
        ''|\#*) ;;
        SPEECH_API_TOKEN=*)
            [ "$candidate" = 'SPEECH_API_TOKEN=' ] && [ "$1" = "$candidate" ] || fail '.env.example must use one unindented, empty SPEECH_API_TOKEN= assignment'
            token_lines=$((token_lines + 1))
            ;;
        SPEECH_API_TOKEN|SPEECH_API_TOKEN[[:space:]]*|export[[:space:]]SPEECH_API_TOKEN*)
            fail '.env.example contains a malformed SPEECH_API_TOKEN setting'
            ;;
    esac
}

token_lines=0
while IFS= read -r line || [ -n "$line" ]; do
    validate_template_token_line "$line"
done < .env.example
[ "$token_lines" -eq 1 ] || fail '.env.example must contain exactly one SPEECH_API_TOKEN setting'

token=$(openssl rand -hex 32 2>/dev/null) || fail 'could not generate a secure API token with openssl'
case "$token" in
    ''|*[!0-9a-f]*) fail 'openssl returned an invalid API token' ;;
esac
[ "${#token}" -eq 64 ] || fail 'openssl returned an invalid API token length'

ensure_private_dir private
ensure_private_dir private/audio
ensure_private_dir private/deployment

temporary_env=$(mktemp .env.init.XXXXXX) || fail 'could not create a temporary private configuration file'
cleanup() {
    if [ -n "${temporary_env:-}" ]; then
        rm -f "$temporary_env"
    fi
}
trap cleanup 0
trap 'exit 1' HUP INT TERM

token_lines=0
while IFS= read -r line || [ -n "$line" ]; do
    validate_template_token_line "$line"
    case "$line" in
        'SPEECH_API_TOKEN=')
            printf 'SPEECH_API_TOKEN=%s\n' "$token"
            ;;
        *) printf '%s\n' "$line" ;;
    esac
done < .env.example > "$temporary_env"
[ "$token_lines" -eq 1 ] || fail '.env.example changed while initialization was running'
chmod 600 "$temporary_env" || fail 'could not set .env permissions to 0600'

if ! ln "$temporary_env" .env 2>/dev/null; then
    if [ -e .env ] || [ -L .env ]; then
        printf '%s\n' 'An .env appeared during initialization; it was preserved unchanged.'
        exit 0
    fi
    fail 'could not create .env without overwriting an existing path'
fi

rm -f "$temporary_env" || fail 'could not clean up the temporary configuration file'
temporary_env=
printf '%s\n' 'Created .env with a private 0600 API token.'
printf '%s\n' 'Created private/, private/audio/ and private/deployment/ with mode 0700.'
printf '%s\n' 'Review model/GPU/network settings. Groq and cloud text credentials are optional; configure them only if enabling those providers.'
printf '%s\n' 'Run make preflight PYTHON=.venv/bin/python before installation.'

#!/usr/bin/env sh
set -eu

if [ "$INIT_CODEX_CONFIG" = "1" ]; then
  mkdir -p "$HOME" "$CODEX_HOME" "$CODEX_HOME/bin"

  config_file="$CODEX_HOME/config.toml"
  default_model="$CODEX_DEFAULT_MODEL"
  if [ ! -f "$config_file" ]; then
    printf 'model = "%s"\n' "$default_model" > "$config_file"
  elif ! grep -Eq '^[[:space:]]*model[[:space:]]*=' "$config_file"; then
    tmp_file="${config_file}.tmp"
    printf 'model = "%s"\n' "$default_model" > "$tmp_file"
    cat "$config_file" >> "$tmp_file"
    mv "$tmp_file" "$config_file"
  fi
fi

exec "$@"

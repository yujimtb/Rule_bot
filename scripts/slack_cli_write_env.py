from __future__ import annotations

import os
from pathlib import Path


REQUIRED_TOKEN_NAMES = ("SLACK_BOT_TOKEN", "SLACK_APP_TOKEN")


def main() -> None:
    updates = {name: _required_env(name) for name in REQUIRED_TOKEN_NAMES}
    env_path = Path(__file__).resolve().parents[1] / ".env"
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    env_path.write_text(_updated_env(lines, updates), encoding="utf-8")
    print("Slack CLI tokens were written to .env without printing secret values.")


def _updated_env(lines: list[str], updates: dict[str, str]) -> str:
    remaining = dict(updates)
    output: list[str] = []
    for line in lines:
        if not line or line.lstrip().startswith("#") or "=" not in line:
            output.append(line)
            continue
        key = line.split("=", 1)[0]
        if key in remaining:
            output.append(f"{key}={remaining.pop(key)}")
        else:
            output.append(line)
    output.extend(f"{key}={value}" for key, value in remaining.items())
    return "\n".join(output) + "\n"


def _required_env(name: str) -> str:
    value = os.environ[name].strip()
    if not value:
        raise ValueError(f"{name} must not be empty")
    return value


if __name__ == "__main__":
    main()

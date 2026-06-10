from __future__ import annotations

from .codex_agent import (  # noqa: F401
    DEFAULT_CANDIDATE_TOP_K,
    DEFAULT_CONTEXT_TOP_K,
    _build_prompt,
    _run_codex,
    _search_candidates,
    main,
)


if __name__ == "__main__":
    main()

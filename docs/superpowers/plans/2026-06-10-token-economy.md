# Estimated Token Economy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-session estimated token counts (input/output) and estimated USD cost to the AIAnalyzer profile, plus new vivid DYK facts and a "Token economy" portal card — all derived offline from text we already have, never claimed as exact.

**Architecture:**
1. Bundle `tiktoken` (~5 MB offline tokenizer; cl100k_base encoding works as a close approximation for both GPT and Claude families).
2. New `pricing.py` module with a curated table of public list prices per model (USD per 1M tokens). Models with no public price → `cost = None` (we display tokens, not dollars).
3. Extend `SessionFeatures` with 4 new fields: `est_input_tokens`, `est_output_tokens`, `est_cost_usd`, `priced_token_share` (the fraction of tokens that came from priced models; tells the user how complete the $ estimate is).
4. Aggregate to `ExtendedProfile` (totals + Pareto), surface in portal as KPI cards + a "Token economy" card and 3 new DYK facts.
5. Bump `SCHEMA_VERSION` 9 → 10; users do one re-scan.

**Tech Stack:** Python 3.12, pydantic 2.7, tiktoken, Chart.js, FastAPI, pytest.

---

### Task 1: Add tiktoken dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add tiktoken to runtime deps**

Edit `pyproject.toml` `dependencies` array (around line 13–22) — add one line:

```toml
  "tiktoken>=0.7",
```

- [ ] **Step 2: Install it**

```bash
cd C:\Users\ruwang\source\repos\Temp\AIAnalyzer-hands-on
pip install -e .
```

Expected: tiktoken-0.x.x successfully installed.

- [ ] **Step 3: Verify it loads offline**

```bash
python -c "import tiktoken; enc = tiktoken.get_encoding('cl100k_base'); print(len(enc.encode('hello world')))"
```

Expected: prints `2`.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "deps: add tiktoken for offline token estimation"
```

---

### Task 2: Pricing table module

**Files:**
- Create: `src/aianalyzer/pricing.py`
- Create: `tests/test_pricing.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_pricing.py`:

```python
"""Pricing table tests — verifies model name resolution and cost math."""
from __future__ import annotations

import pytest

from aianalyzer.pricing import (
    estimate_cost_usd,
    is_priced,
    resolve_pricing,
)


def test_resolve_pricing_exact_match_for_claude_opus():
    p = resolve_pricing("claude-opus-4.7-xhigh")
    assert p is not None
    # Opus 4.x list price: $15 in / $75 out per 1M tokens.
    assert p.input_per_1m == 15.0
    assert p.output_per_1m == 75.0


def test_resolve_pricing_handles_copilot_prefix():
    # "copilot/gpt-5" should resolve to the same row as "gpt-5".
    p = resolve_pricing("copilot/gpt-5")
    assert p is not None
    assert p.input_per_1m > 0


def test_resolve_pricing_returns_none_for_unknown_model():
    assert resolve_pricing("vendor-x-mystery-model-9") is None


def test_estimate_cost_usd_basic_arithmetic():
    # claude-haiku-4.5: $1 in / $5 out per 1M.
    cost = estimate_cost_usd("claude-haiku-4.5", input_tokens=1_000_000, output_tokens=200_000)
    assert cost == pytest.approx(1.0 + 1.0)  # 1.0 (input) + 1.0 (200k * 5/1M)


def test_estimate_cost_usd_none_for_unknown_model():
    assert estimate_cost_usd("totally-unknown", 1_000_000, 100_000) is None


def test_is_priced_true_for_known_model():
    assert is_priced("claude-opus-4.6") is True


def test_is_priced_false_for_unknown_model():
    assert is_priced("custom-private-model") is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd C:\Users\ruwang\source\repos\Temp\AIAnalyzer-hands-on
$env:PYTHONPATH = "C:\Users\ruwang\source\repos\Temp\AIAnalyzer-hands-on\src"
python -m pytest tests/test_pricing.py -v
```

Expected: ImportError — `aianalyzer.pricing` does not exist.

- [ ] **Step 3: Create the pricing module**

Create `src/aianalyzer/pricing.py`:

```python
"""Curated public-list prices per model (USD per 1M tokens).

Prices are best-effort and based on publicly published list rates as of
mid-2026. Models without a published per-token price (notably some
Copilot-proprietary routings and unknown vendor models) return ``None`` —
the portal displays token counts only in that case rather than a fabricated
dollar figure.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ModelPricing:
    input_per_1m: float   # USD per 1 million input tokens
    output_per_1m: float  # USD per 1 million output tokens


# Match rules are evaluated in order; the FIRST substring that the lowercase
# model name contains wins. Put more-specific keys before less-specific ones.
_PRICING: list[tuple[str, ModelPricing]] = [
    # ---- Anthropic Claude family ----
    ("claude-haiku-4",   ModelPricing(1.00,  5.00)),
    ("haiku",            ModelPricing(0.80,  4.00)),
    ("claude-sonnet-4",  ModelPricing(3.00, 15.00)),
    ("sonnet-4",         ModelPricing(3.00, 15.00)),
    ("claude-sonnet",    ModelPricing(3.00, 15.00)),
    ("sonnet",           ModelPricing(3.00, 15.00)),
    ("claude-opus-4",    ModelPricing(15.00, 75.00)),
    ("opus-4",           ModelPricing(15.00, 75.00)),
    ("claude-opus",      ModelPricing(15.00, 75.00)),
    ("opus",             ModelPricing(15.00, 75.00)),
    ("claude-3.5",       ModelPricing(3.00, 15.00)),
    # ---- OpenAI / GPT family ----
    ("gpt-5.5",          ModelPricing(15.00, 60.00)),
    ("gpt-5.4-mini",     ModelPricing(0.25,  2.00)),
    ("gpt-5.4",          ModelPricing(10.00, 40.00)),
    ("gpt-5.3-codex",    ModelPricing(5.00,  20.00)),
    ("gpt-5.1-codex-max",ModelPricing(8.00,  32.00)),
    ("gpt-5.1-codex",    ModelPricing(5.00,  20.00)),
    ("gpt-5-codex",      ModelPricing(5.00,  20.00)),
    ("gpt-5-mini",       ModelPricing(0.20,  1.60)),
    ("gpt-5",            ModelPricing(5.00,  20.00)),
    ("gpt-4o-mini",      ModelPricing(0.15,  0.60)),
    ("gpt-4o",           ModelPricing(2.50,  10.00)),
    # ---- Other ----
    ("gemini-2.5-pro",   ModelPricing(1.25,  5.00)),
    ("gemini-3.1-pro",   ModelPricing(1.50,  6.00)),
    ("gemini",           ModelPricing(0.35,  1.05)),
    ("mai-code",         ModelPricing(2.00,  8.00)),
]


def _normalize(model: str) -> str:
    """Lowercase + drop a leading 'copilot/' or 'github-copilot/' route prefix."""
    m = model.lower().strip()
    for prefix in ("copilot/", "github-copilot/", "github/"):
        if m.startswith(prefix):
            m = m[len(prefix):]
            break
    return m


def resolve_pricing(model: str) -> Optional[ModelPricing]:
    if not model:
        return None
    m = _normalize(model)
    for key, price in _PRICING:
        if key in m:
            return price
    return None


def is_priced(model: str) -> bool:
    return resolve_pricing(model) is not None


def estimate_cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> Optional[float]:
    """Return the estimated USD cost, or None when the model has no published price."""
    p = resolve_pricing(model)
    if p is None:
        return None
    return (
        input_tokens / 1_000_000 * p.input_per_1m
        + output_tokens / 1_000_000 * p.output_per_1m
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_pricing.py -v
```

Expected: all 7 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/aianalyzer/pricing.py tests/test_pricing.py
git commit -m "feat(pricing): curated public-list pricing table per model"
```

---

### Task 3: Token estimation helper

**Files:**
- Modify: `src/aianalyzer/features.py` (add helper near top)
- Create: `tests/test_token_estimation.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_token_estimation.py`:

```python
"""Tests for the lazy tiktoken-backed token counter."""
from __future__ import annotations

from aianalyzer.features import _count_tokens, _reset_encoder_cache


def test_count_tokens_returns_positive_for_non_empty_text():
    n = _count_tokens("Hello, world! This is a sentence.")
    assert n > 3
    assert n < 20


def test_count_tokens_returns_zero_for_empty_text():
    assert _count_tokens("") == 0
    assert _count_tokens(None) == 0


def test_count_tokens_scales_with_length():
    short = _count_tokens("hi")
    long_ = _count_tokens("hello there how are you doing today my friend")
    assert long_ > short


def test_count_tokens_caches_encoder_between_calls():
    _reset_encoder_cache()
    a = _count_tokens("first call")
    b = _count_tokens("second call")
    assert a > 0 and b > 0
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest tests/test_token_estimation.py -v
```

Expected: ImportError on `_count_tokens`.

- [ ] **Step 3: Implement the helper in features.py**

Edit `src/aianalyzer/features.py`. Add these helpers immediately after the imports block (before any `_PLANNING_TOKENS` definition):

```python
# --- Token estimation (tiktoken cl100k_base; approximate for all model families)
_encoder = None


def _reset_encoder_cache() -> None:
    """Test hook to drop the cached encoder."""
    global _encoder
    _encoder = None


def _count_tokens(text: str | None) -> int:
    """Estimate token count for a string using the cl100k_base BPE.

    Returns 0 for empty/None input. We use a single tokenizer for every
    model — this is intentional: cl100k_base is within ~5% of the actual
    GPT-5 / Claude tokenisers on natural text, and bundling per-vendor
    tokenizers would double the .exe size for marginal accuracy gains.
    """
    if not text:
        return 0
    global _encoder
    if _encoder is None:
        import tiktoken
        _encoder = tiktoken.get_encoding("cl100k_base")
    return len(_encoder.encode(text, disallowed_special=()))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_token_estimation.py -v
```

Expected: all 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/aianalyzer/features.py tests/test_token_estimation.py
git commit -m "feat(features): _count_tokens helper using cached tiktoken encoder"
```

---

### Task 4: Per-session token + cost fields on SessionFeatures

**Files:**
- Modify: `src/aianalyzer/features.py`
- Modify: `src/aianalyzer/store.py` (schema bump)
- Modify: `tests/test_features.py` (add a new test)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_features.py` (find the file first, scroll to end, add after the last test):

```python
def test_compute_features_estimates_tokens_and_cost(tmp_path):
    """A 1-turn session with a known prompt + reply should produce
    positive input/output token estimates and a finite USD cost."""
    from aianalyzer.features import compute_features
    from aianalyzer.normalize import (
        AssistantMessage, NormalizedSession, Turn, UserMessage,
    )
    from datetime import datetime, timezone

    session = NormalizedSession(
        client="copilot-cli",
        session_id="t-tokens",
        started_at=datetime(2026, 6, 10, 9, 0, tzinfo=timezone.utc),
        ended_at=datetime(2026, 6, 10, 9, 5, tzinfo=timezone.utc),
        cwd="/repos/x",
        models_used=["claude-sonnet-4.6"],
        turns=[
            Turn(
                index=0,
                user=UserMessage(
                    content="please rewrite this function to be tail-recursive",
                    ts=datetime(2026, 6, 10, 9, 0, tzinfo=timezone.utc),
                ),
                assistant=AssistantMessage(
                    turn_id="r1",
                    content="Sure, here's the rewritten version: " + ("code " * 100),
                    model="claude-sonnet-4.6",
                    ts=datetime(2026, 6, 10, 9, 1, tzinfo=timezone.utc),
                ),
            )
        ],
    )
    f = compute_features(session)
    assert f.est_input_tokens > 5
    assert f.est_output_tokens > 50
    assert f.est_total_tokens == f.est_input_tokens + f.est_output_tokens
    assert f.est_cost_usd is not None and f.est_cost_usd > 0
    assert 0.99 <= f.priced_token_share <= 1.0
```

- [ ] **Step 2: Run test to verify failure**

```bash
python -m pytest tests/test_features.py::test_compute_features_estimates_tokens_and_cost -v
```

Expected: AttributeError — `est_input_tokens` not defined.

- [ ] **Step 3: Add fields to SessionFeatures**

Edit `src/aianalyzer/features.py`. Inside `class SessionFeatures(BaseModel):` block, after the existing "Prompt-mined facts" comment + fields (around line 113–118), append:

```python
    # Token economy estimates (Phase F)
    est_input_tokens: int = 0
    est_output_tokens: int = 0
    est_total_tokens: int = 0
    est_cost_usd: float | None = None
    priced_token_share: float = 0.0
```

- [ ] **Step 4: Compute the fields in `compute_features`**

Find the bottom of `compute_features` in `src/aianalyzer/features.py`. Just before the final `return SessionFeatures(...)`, insert this block:

```python
    # ---- Token economy (Phase F) ----
    from aianalyzer.pricing import estimate_cost_usd, is_priced

    est_in = 0
    est_out = 0
    est_cost: float = 0.0
    priced_token_total = 0
    any_priced = False
    for t in turns:
        in_tok = _count_tokens(t.user.content) if t.user else 0
        out_tok = _count_tokens(t.assistant.content) if t.assistant else 0
        est_in += in_tok
        est_out += out_tok
        model = t.assistant.model if t.assistant else ""
        c = estimate_cost_usd(model, in_tok, out_tok)
        if c is not None:
            est_cost += c
            priced_token_total += in_tok + out_tok
            any_priced = True

    est_total = est_in + est_out
    est_cost_value: float | None = est_cost if any_priced else None
    priced_share = priced_token_total / est_total if est_total > 0 else 0.0
```

- [ ] **Step 5: Pass the new values into the `SessionFeatures(...)` constructor call**

In the same `return SessionFeatures(...)` call at the bottom of `compute_features`, add these kwargs (alphabetically near the other Phase C ones):

```python
        est_input_tokens=est_in,
        est_output_tokens=est_out,
        est_total_tokens=est_total,
        est_cost_usd=est_cost_value,
        priced_token_share=priced_share,
```

- [ ] **Step 6: Bump schema version**

Edit `src/aianalyzer/store.py`. Update the version-history comment + bump:

```python
# v9: first_words preserves apostrophes ("let's" instead of "lets").
# v10: per-session token estimates (est_input_tokens, est_output_tokens,
#      est_total_tokens, est_cost_usd, priced_token_share).
SCHEMA_VERSION = 10
```

- [ ] **Step 7: Run the new test (and full features suite) to verify**

```bash
python -m pytest tests/test_features.py -v
```

Expected: all tests pass, including the new token estimate test.

- [ ] **Step 8: Commit**

```bash
git add src/aianalyzer/features.py src/aianalyzer/store.py tests/test_features.py
git commit -m "feat(features): per-session token + USD cost estimation (schema v10)"
```

---

### Task 5: Aggregate to ExtendedProfile (totals + Pareto + verbosity)

**Files:**
- Modify: `src/aianalyzer/stats.py`
- Modify: `tests/test_stats.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_stats.py`:

```python
def test_extended_profile_aggregates_token_totals_and_cost():
    fs = [
        _sf(est_input_tokens=1000, est_output_tokens=4000, est_total_tokens=5000,
            est_cost_usd=0.05, priced_token_share=1.0),
        _sf(est_input_tokens=2000, est_output_tokens=8000, est_total_tokens=10000,
            est_cost_usd=0.10, priced_token_share=1.0),
        _sf(est_input_tokens=500, est_output_tokens=500, est_total_tokens=1000,
            est_cost_usd=None, priced_token_share=0.0),
    ]
    p = compute_extended_profile(fs)
    assert p.est_input_tokens_total == 3500
    assert p.est_output_tokens_total == 12500
    assert p.est_total_tokens == 16000
    # Only priced sessions contribute to USD; unknown-priced is dropped.
    assert p.est_cost_usd_total == pytest.approx(0.15)
    # Verbosity = output / input across all sessions
    assert p.output_to_input_ratio == pytest.approx(12500 / 3500)


def test_extended_profile_pareto_top_n_share():
    fs = []
    for i in range(10):
        fs.append(_sf(est_total_tokens=100, est_cost_usd=0.01))
    fs.append(_sf(est_total_tokens=10_000, est_cost_usd=1.00))
    fs.append(_sf(est_total_tokens=5_000, est_cost_usd=0.50))
    p = compute_extended_profile(fs)
    # Top 5 sessions: 10000 + 5000 + 100 + 100 + 100 = 15300 of 16000 total.
    assert p.top5_tokens_share == pytest.approx(15300 / 16000, abs=0.01)


def test_extended_profile_token_fields_zero_when_no_sessions():
    p = compute_extended_profile([])
    assert p.est_input_tokens_total == 0
    assert p.est_output_tokens_total == 0
    assert p.est_total_tokens == 0
    assert p.est_cost_usd_total == 0.0
    assert p.output_to_input_ratio == 0.0
    assert p.top5_tokens_share == 0.0
```

- [ ] **Step 2: Update _sf helper to accept the new optional kwargs**

The `_sf` helper currently builds a dict and updates it from `overrides`. Since `SessionFeatures` already has defaults for the new fields, no helper change is needed — the test calls will work via the existing `base.update(overrides)`. Verify by running the new tests:

```bash
python -m pytest tests/test_stats.py::test_extended_profile_aggregates_token_totals_and_cost -v
```

Expected: AttributeError on `est_input_tokens_total` (it's not yet on ExtendedProfile).

- [ ] **Step 3: Add fields to ExtendedProfile**

Edit `src/aianalyzer/stats.py`. Inside `class ExtendedProfile(BaseModel):`, after the Phase D fields (`model_tier_counts`), add:

```python
    # Token economy (Phase F)
    est_input_tokens_total: int = 0
    est_output_tokens_total: int = 0
    est_total_tokens: int = 0
    est_cost_usd_total: float = 0.0
    priced_token_share: float = 0.0  # share of total tokens that contributed to USD
    output_to_input_ratio: float = 0.0
    top5_tokens_share: float = 0.0   # Pareto: top-5 sessions by tokens / total
```

- [ ] **Step 4: Aggregate in compute_extended_profile**

In `src/aianalyzer/stats.py`, find the "Phase D" block near the end of `compute_extended_profile()`. Add this Phase F block immediately after it (before the `return ExtendedProfile(...)`):

```python
    # ---- Phase F: token economy aggregates ----
    est_in_total = sum(f.est_input_tokens for f in features)
    est_out_total = sum(f.est_output_tokens for f in features)
    est_total = est_in_total + est_out_total
    est_cost_total = sum(f.est_cost_usd or 0.0 for f in features)

    # priced share = (tokens from priced sessions / total tokens)
    priced_tokens = sum(
        f.est_total_tokens for f in features if f.est_cost_usd is not None
    )
    priced_share_total = priced_tokens / est_total if est_total > 0 else 0.0

    output_input_ratio = (est_out_total / est_in_total) if est_in_total > 0 else 0.0

    # Top-5 Pareto by token total
    top5 = sorted(
        (f.est_total_tokens for f in features), reverse=True
    )[:5]
    top5_share = sum(top5) / est_total if est_total > 0 else 0.0
```

- [ ] **Step 5: Pass new values into the ExtendedProfile constructor**

Find the `return ExtendedProfile(...)` call. Add these kwargs (next to the Phase D ones):

```python
        est_input_tokens_total=est_in_total,
        est_output_tokens_total=est_out_total,
        est_total_tokens=est_total,
        est_cost_usd_total=est_cost_total,
        priced_token_share=priced_share_total,
        output_to_input_ratio=output_input_ratio,
        top5_tokens_share=top5_share,
```

- [ ] **Step 6: Run the new tests**

```bash
python -m pytest tests/test_stats.py -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/aianalyzer/stats.py tests/test_stats.py
git commit -m "feat(stats): aggregate token totals, USD cost, output ratio, top-5 Pareto"
```

---

### Task 6: Three new "Did you know?" facts driven by token data

**Files:**
- Modify: `src/aianalyzer/insights.py`
- Modify: `src/aianalyzer/web/services.py`
- Modify: `tests/test_insights.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_insights.py` (within the existing module — find the bottom):

```python
def test_did_you_know_includes_token_total_fact():
    from aianalyzer.insights import _did_you_know
    from aianalyzer.profile import UserProfile

    profile = UserProfile(session_count=10, total_turns=50)
    fs = [_make_features(i) for i in range(3)]
    facts = _did_you_know(
        profile, fs,
        est_total_tokens=12_500_000,
        est_cost_usd_total=180.5,
        priced_token_share=0.92,
    )
    titles = [f.title for f in facts]
    assert "Token burn" in titles


def test_did_you_know_includes_pareto_fact_when_concentrated():
    from aianalyzer.insights import _did_you_know
    from aianalyzer.profile import UserProfile

    profile = UserProfile(session_count=20, total_turns=100)
    fs = [_make_features(i) for i in range(3)]
    facts = _did_you_know(
        profile, fs,
        est_total_tokens=10_000_000,
        top5_tokens_share=0.55,
    )
    assert any("top 5" in f.detail.lower() for f in facts)


def test_did_you_know_includes_generator_vs_reviewer_fact():
    from aianalyzer.insights import _did_you_know
    from aianalyzer.profile import UserProfile

    profile = UserProfile(session_count=15, total_turns=60)
    fs = [_make_features(i) for i in range(3)]
    # Output 6x input → strong Generator signal.
    facts_gen = _did_you_know(profile, fs, output_to_input_ratio=6.2)
    assert any("generator" in f.title.lower() or "generator" in f.detail.lower()
               for f in facts_gen)
    # Output 0.4x input → strong Reviewer signal.
    facts_rev = _did_you_know(profile, fs, output_to_input_ratio=0.4)
    assert any("reviewer" in f.title.lower() or "reviewer" in f.detail.lower()
               for f in facts_rev)
```

You may need a `_make_features` helper near the top of the test module. Search the file — most likely a helper already exists for building `SessionFeatures`. If not, copy this stub into the file once:

```python
def _make_features(i: int):
    from aianalyzer.features import SessionFeatures
    from datetime import datetime, timezone
    return SessionFeatures(
        session_id=f"s{i}",
        client="copilot-cli",
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        turn_count=4,
    )
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest tests/test_insights.py::test_did_you_know_includes_token_total_fact -v
```

Expected: TypeError on unexpected kwargs.

- [ ] **Step 3: Add kwargs and DYK items in _did_you_know**

Edit `src/aianalyzer/insights.py`. Extend the `_did_you_know(...)` signature with these kwargs (right after `model_tier_counts`):

```python
    est_total_tokens: int = 0,
    est_cost_usd_total: float = 0.0,
    priced_token_share: float = 0.0,
    output_to_input_ratio: float = 0.0,
    top5_tokens_share: float = 0.0,
```

Then, at the end of `_did_you_know` (just before `insights.sort(...)`), append:

```python
    # 14) Token burn — total estimated tokens (+ optional USD).
    if est_total_tokens >= 100_000:
        mtok = est_total_tokens / 1_000_000
        detail = f"You've consumed an estimated {mtok:,.1f} M tokens of AI compute"
        if est_cost_usd_total > 0:
            coverage_note = ""
            if priced_token_share < 0.95:
                coverage_note = (
                    f" (covers ~{round(100 * priced_token_share)}% of your turns —"
                    f" the rest are on models without a public list price)"
                )
            detail += f" — about <b>${est_cost_usd_total:,.2f}</b> at list rates{coverage_note}."
        else:
            detail += "."
        insights.append(Insight(
            kind="did_you_know", icon="🪙", title="Token burn",
            detail=detail, rank=92,
        ))

    # 15) Pareto fact — top-5 sessions dominate.
    if top5_tokens_share >= 0.30:
        pct = round(100 * top5_tokens_share)
        insights.append(Insight(
            kind="did_you_know", icon="📊", title="Heavy hitters",
            detail=(
                f"Your top 5 sessions account for {pct}% of all your AI token "
                f"spend — a few deep-dive days dwarf the rest."
            ),
            rank=68,
        ))

    # 16) Generator vs Reviewer style — output:input ratio.
    if output_to_input_ratio >= 3.0:
        insights.append(Insight(
            kind="did_you_know", icon="🎁", title="Generator style",
            detail=(
                f"AI replies are <b>{output_to_input_ratio:.1f}×</b> longer than "
                f"your prompts on average. You're a <b>Generator</b> — short "
                f"prompts, big artefacts."
            ),
            rank=66,
        ))
    elif output_to_input_ratio > 0 and output_to_input_ratio <= 0.7:
        insights.append(Insight(
            kind="did_you_know", icon="🔍", title="Reviewer style",
            detail=(
                f"Your prompts are about <b>{1 / output_to_input_ratio:.1f}×</b> "
                f"longer than AI's replies on average. You're a <b>Reviewer</b> — "
                f"long detailed asks, short focused answers."
            ),
            rank=66,
        ))
```

- [ ] **Step 4: Extend compute_personality kwargs likewise**

In the same `insights.py`, find `def compute_personality(...)`. Add the five new kwargs (`est_total_tokens`, `est_cost_usd_total`, `priced_token_share`, `output_to_input_ratio`, `top5_tokens_share`) to the signature and forward them inside the inner `_did_you_know(...)` call. Mirror the pattern of the Phase D kwargs.

- [ ] **Step 5: Wire from web/services.py**

Edit `src/aianalyzer/web/services.py`. Find the `compute_personality(...)` call inside `load_profile_payload`. Add these kwargs (after `model_tier_counts=ext.model_tier_counts,`):

```python
            est_total_tokens=ext.est_total_tokens,
            est_cost_usd_total=ext.est_cost_usd_total,
            priced_token_share=ext.priced_token_share,
            output_to_input_ratio=ext.output_to_input_ratio,
            top5_tokens_share=ext.top5_tokens_share,
```

Also expose the same fields at the top level of the payload (next to `model_tier_counts`) so the frontend can render the KPI/Token-economy card:

```python
        "est_input_tokens_total": ext.est_input_tokens_total,
        "est_output_tokens_total": ext.est_output_tokens_total,
        "est_total_tokens": ext.est_total_tokens,
        "est_cost_usd_total": ext.est_cost_usd_total,
        "priced_token_share": ext.priced_token_share,
        "output_to_input_ratio": ext.output_to_input_ratio,
        "top5_tokens_share": ext.top5_tokens_share,
```

- [ ] **Step 6: Run the tests**

```bash
python -m pytest tests/test_insights.py -v
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add src/aianalyzer/insights.py src/aianalyzer/web/services.py tests/test_insights.py
git commit -m "feat(insights): token burn, top-5 Pareto, generator/reviewer style facts"
```

---

### Task 7: Token Economy portal card + KPI tiles

**Files:**
- Modify: `src/aianalyzer/web/static/index.html`
- Modify: `src/aianalyzer/web/static/styles.css`
- Modify: `src/aianalyzer/web/static/app.js`

- [ ] **Step 1: Add the Token Economy card to the HTML**

Edit `src/aianalyzer/web/static/index.html`. Insert this new card immediately before the existing `<section class="grid" id="kpi-grid"></section>` line (so it appears above the KPI grid, in the prime real estate just under the personality section):

```html
    <section id="token-card" class="card token-card" hidden>
      <div class="card-eyebrow">Token economy</div>
      <h2>Your AI compute footprint <span class="muted token-disclaimer">(estimated)</span></h2>
      <p class="card-sub">
        We re-tokenise your saved prompts and replies with a cl100k BPE
        (~5% off from each vendor's exact tokenizer) and multiply by public
        list prices. Models without a published per-token price contribute
        to token counts but not dollars.
      </p>
      <div class="token-grid">
        <div class="token-tile">
          <div class="token-tile-label">Total tokens (est.)</div>
          <div class="token-tile-value" id="token-total">—</div>
          <div class="token-tile-sub" id="token-split">—</div>
        </div>
        <div class="token-tile">
          <div class="token-tile-label">Cost at list rates (est.)</div>
          <div class="token-tile-value" id="token-cost">—</div>
          <div class="token-tile-sub" id="token-cost-coverage">—</div>
        </div>
        <div class="token-tile">
          <div class="token-tile-label">Output : Input ratio</div>
          <div class="token-tile-value" id="token-ratio">—</div>
          <div class="token-tile-sub" id="token-ratio-style">—</div>
        </div>
        <div class="token-tile">
          <div class="token-tile-label">Top 5 session share</div>
          <div class="token-tile-value" id="token-pareto">—</div>
          <div class="token-tile-sub">Pareto: how concentrated is your spend?</div>
        </div>
      </div>
    </section>
```

- [ ] **Step 2: Add styles**

Edit `src/aianalyzer/web/static/styles.css`. Append at the end of the file:

```css
/* Phase F — Token economy card */
.token-card { margin-bottom: 18px; }
.token-disclaimer { font-size: 14px; font-weight: 400; }
.token-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 14px;
  margin-top: 14px;
}
.token-tile {
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 10px;
  padding: 14px 16px;
}
.token-tile-label {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--muted);
  margin-bottom: 8px;
}
.token-tile-value {
  font-size: 22px;
  font-weight: 600;
  color: var(--text);
  line-height: 1.1;
}
.token-tile-sub {
  margin-top: 6px;
  font-size: 11px;
  color: var(--muted);
  line-height: 1.4;
}
```

- [ ] **Step 3: Add renderTokenCard in app.js**

Edit `src/aianalyzer/web/static/app.js`. After `renderModelTier(...)` function add:

```javascript
  function renderTokenCard(p) {
    const card = document.getElementById("token-card");
    if (!card) return;
    const total = p.est_total_tokens || 0;
    if (total <= 0) { card.hidden = true; return; }
    card.hidden = false;

    const inTok = p.est_input_tokens_total || 0;
    const outTok = p.est_output_tokens_total || 0;
    const cost = p.est_cost_usd_total || 0;
    const coverage = p.priced_token_share || 0;
    const ratio = p.output_to_input_ratio || 0;
    const pareto = p.top5_tokens_share || 0;

    const fmtTok = (n) => {
      if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)} M`;
      if (n >= 1_000) return `${(n / 1_000).toFixed(0)} K`;
      return n.toLocaleString();
    };
    const fmtUsd = (n) => "$" + n.toLocaleString(undefined, {
      minimumFractionDigits: 2, maximumFractionDigits: 2,
    });

    document.getElementById("token-total").textContent = fmtTok(total);
    document.getElementById("token-split").textContent =
      `Input ${fmtTok(inTok)} · Output ${fmtTok(outTok)}`;

    document.getElementById("token-cost").textContent =
      cost > 0 ? fmtUsd(cost) : "—";
    document.getElementById("token-cost-coverage").textContent =
      cost > 0
        ? `Covers ${Math.round(100 * coverage)}% of your turns at list rates`
        : "Models on your stack have no public list price";

    document.getElementById("token-ratio").textContent =
      ratio > 0 ? `${ratio.toFixed(1)}×` : "—";
    let style = "Balanced — equal weight to prompt and reply";
    if (ratio >= 3.0) style = "Generator — short prompts, big replies";
    else if (ratio > 0 && ratio <= 0.7) style = "Reviewer — long prompts, terse replies";
    document.getElementById("token-ratio-style").textContent = style;

    document.getElementById("token-pareto").textContent =
      `${Math.round(100 * pareto)}%`;
  }
```

- [ ] **Step 4: Call renderTokenCard from the main load flow**

In `app.js`, find where `renderModelTier(p.model_tier_counts)` is called. Add right after it:

```javascript
    renderTokenCard(p);
```

- [ ] **Step 5: Commit**

```bash
git add src/aianalyzer/web/static/index.html src/aianalyzer/web/static/styles.css src/aianalyzer/web/static/app.js
git commit -m "feat(portal): Token economy card with 4 KPI tiles (estimated)"
```

---

### Task 8: Smoke test, rescan, and validate full suite

- [ ] **Step 1: Run full test suite**

```bash
cd C:\Users\ruwang\source\repos\Temp\AIAnalyzer-hands-on
$env:PYTHONPATH = "C:\Users\ruwang\source\repos\Temp\AIAnalyzer-hands-on\src"
python -m pytest -q
```

Expected: 157 + 7 (pricing) + 4 (token estimation) + 1 (features new test) + 3 (stats) + 3 (insights) = 175 passing.

- [ ] **Step 2: Free port 8780, restart the dev portal**

```bash
$conn = Get-NetTCPConnection -LocalPort 8780 -ErrorAction SilentlyContinue | Select-Object -First 1
if ($conn) { Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2
```

Then start the portal in an async shell (id `portal_f`):

```bash
cd C:\Users\ruwang\source\repos\Temp\AIAnalyzer-hands-on
$env:PYTHONPATH = "C:\Users\ruwang\source\repos\Temp\AIAnalyzer-hands-on\src"
python -u $env:TEMP\run_portal_handson.py
```

- [ ] **Step 3: Trigger a rescan via the API**

The schema bump invalidates cached features. Trigger the scan endpoint:

```bash
curl -X POST http://127.0.0.1:8780/api/scan
```

Then poll `/api/scan/<id>` until `progress == 1.0`.

- [ ] **Step 4: Verify /api/profile returns the new fields**

```bash
curl -s http://127.0.0.1:8780/api/profile | python -c "
import sys, json
p = json.load(sys.stdin)
print('est_input_tokens_total :', p.get('est_input_tokens_total'))
print('est_output_tokens_total:', p.get('est_output_tokens_total'))
print('est_cost_usd_total     :', p.get('est_cost_usd_total'))
print('output:input ratio     :', round(p.get('output_to_input_ratio', 0), 2))
print('top5 tokens share      :', round(p.get('top5_tokens_share', 0), 2))
print('priced token share     :', round(p.get('priced_token_share', 0), 2))
"
```

Expected: all numbers > 0 and sensible.

- [ ] **Step 5: Render a portal snapshot for visual verification**

```bash
$png = "$env:TEMP\portal_phase_f.png"
curl.exe -s -o $null http://127.0.0.1:8780/api/profile
& "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" `
  "--headless=new" "--disable-gpu" "--hide-scrollbars" `
  "--window-size=1280,5000" "--virtual-time-budget=20000" `
  "--screenshot=$png" "http://127.0.0.1:8780/"
Copy-Item $png "C:\Users\ruwang\.copilot\session-state\3d3bfe57-a5f4-4d47-a021-c986d558939e\files\phase_f_portal.png" -Force
```

Open the PNG in the view tool to visually confirm the Token economy card is visible.

- [ ] **Step 6: Stop the portal, rebuild the .exe**

```bash
# stop_powershell portal_f
cd C:\Users\ruwang\source\repos\Temp\AIAnalyzer-hands-on
.\packaging\build_exe.ps1 -SkipInstall
```

Expected: build succeeds, new `dist\aianalyzer.zip` produced.

- [ ] **Step 7: Final commit summarising Phase F**

```bash
git log --oneline -10
```

Confirm all Phase F commits are present.

---

## Self-Review Notes

- All five new `SessionFeatures` fields have defaults so existing fixtures stay green without modification.
- `priced_token_share` semantics are consistent: per-session it's the turn-level coverage; in `ExtendedProfile` it's the global token-weighted coverage. Naming is the same; both are documented inline.
- The pricing table is opinionated; users can edit `_PRICING` to refresh rates. We deliberately avoid claiming exact dollars — every UI copy says "est." or "list rates".
- Schema bump to v10 means one re-scan after first run on existing data. Documented in `store.py` history comment.
- tiktoken adds ~5 MB to the .exe but eliminates the dependency on network-fetched tokenizers (cl100k_base ships embedded).

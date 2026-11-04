"""Plafonds journaliers Token Factory."""
from datetime import datetime, timezone

import llm_budget


def test_estimate_usd_matches_plan_grid():
    # Super : 0,30 $ / M in, 0,90 $ / M out → 1000 + 100 tokens = 0,00039 $
    assert llm_budget.estimate_usd("write", 1000, 100) == 0.00039
    assert llm_budget.estimate_usd("fast", 1_000_000, 0) == 0.06
    assert llm_budget.estimate_usd("judge", 0, 1_000_000) == 3.0


def test_record_increments_tokens_calls_usd():
    assert llm_budget.get_usage("write")["tokens"] == 0
    out = llm_budget.record("write", 2000, 300)
    assert out["tokens"] == 2300
    assert out["calls"] == 1
    assert out["usd"] == llm_budget.estimate_usd("write", 2000, 300)
    out2 = llm_budget.record("write", 100, 0)
    assert out2["tokens"] == 2400 and out2["calls"] == 2
    st = llm_budget.status()
    assert st["write"]["tokens"] == 2400
    assert st["write"]["calls"] == 2
    assert st["fast"]["tokens"] == 0 and st["judge"]["calls"] == 0


def test_allow_false_at_cap(monkeypatch):
    monkeypatch.setenv("NAVIGUIDE_LLM_DAILY_TOKENS_WRITE", "100")
    assert llm_budget.allow("write") is True
    llm_budget.record("write", 60, 40)
    assert llm_budget.get_usage("write")["tokens"] == 100
    assert llm_budget.allow("write") is False
    llm_budget.record("write", 10, 0)  # counter may grow; still capped
    assert llm_budget.allow("write") is False


def test_models_and_sources_are_overridable(monkeypatch):
    assert llm_budget.model_for("fast") == "nvidia/Nemotron-3_5-Lightning"
    assert llm_budget.model_for("write") == "nvidia/Nemotron-3.5-Super-VL"
    assert llm_budget.model_for("deep") == "nvidia/Nemotron-3-Ultra-550b-a55b"
    assert llm_budget.model_for("judge") == "nvidia/Nemotron-3-Ultra-550b-a55b"
    assert llm_budget.source_for("write") == "nemotron-super-vl"
    assert llm_budget.source_for("deep") == "nemotron-ultra"
    monkeypatch.setenv("NAVIGUIDE_TF_MODEL_WRITE", "nvidia/nemotron-3-nano-30b-a3b")
    assert llm_budget.model_for("write") == "nvidia/nemotron-3-nano-30b-a3b"
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    llm_budget.record("fast", 1, 1)
    import pearl_store
    assert pearl_store.kv_get("llm-budget", f"{day}:fast")["value"]["calls"] == 1


def test_allow_tavily_respects_daily_cap(monkeypatch):
    monkeypatch.setenv("NAVIGUIDE_TAVILY_DAILY_CREDITS", "1")
    assert llm_budget.allow_tavily() is True
    llm_budget.record_tavily(1)
    assert llm_budget.tavily_usage()["credits"] == 1
    assert llm_budget.allow_tavily() is False


def test_remember_source_skips_cache():
    llm_budget.remember_source("nemotron-super")
    assert llm_budget.last_source() == "nemotron-super"
    llm_budget.remember_source("cache")
    assert llm_budget.last_source() == "nemotron-super"
    st = llm_budget.status()
    assert st["lastSource"] == "nemotron-super"


def test_remember_cascade_error_is_in_status():
    llm_budget.remember_cascade_errors([
        {"provider": "tokenfactory", "reason": "tokenfactory HTTP 422 {\"error\":\"empty\"}"},
        {"provider": "nim", "reason": "NVIDIA_API_KEY missing"},
    ])
    err = llm_budget.last_error()
    assert err["provider"] == "tokenfactory"
    assert "422" in err["reason"]
    st = llm_budget.status()
    assert st["lastError"]["provider"] == "tokenfactory"
    assert [h["provider"] for h in st["lastErrors"]] == ["tokenfactory", "nim"]


def test_mode_off_forbids_every_call(monkeypatch):
    monkeypatch.setenv("NAVIGUIDE_LLM_MODE", "off")
    for tier in ("nano", "fast", "write", "deep", "judge"):
        assert llm_budget.allow(tier) is False


def test_on_demand_forbids_background_but_allows_request(monkeypatch):
    monkeypatch.delenv("NAVIGUIDE_LLM_MODE", raising=False)
    monkeypatch.setenv("NAVIGUIDE_LLM_DAILY_TOKENS_WRITE", "1000")
    assert llm_budget.mode() == "on-demand"
    assert llm_budget.allow("write") is True, "une action de l'utilisateur peut appeler"
    with llm_budget.background():
        assert llm_budget.allow("write") is False, "l'arrière-plan ne dépense rien"
    assert llm_budget.allow("write") is True
    monkeypatch.setenv("NAVIGUIDE_LLM_BACKGROUND", "1")
    assert llm_budget.allow("write") is False, "processus marqué arrière-plan (remplisseur)"


def test_mode_all_allows_background(monkeypatch):
    monkeypatch.setenv("NAVIGUIDE_LLM_MODE", "all")
    monkeypatch.setenv("NAVIGUIDE_LLM_DAILY_TOKENS_WRITE", "1000")
    with llm_budget.background():
        assert llm_budget.allow("write") is True


def test_judge_cap_default_is_judge_sized(monkeypatch):
    monkeypatch.delenv("NAVIGUIDE_LLM_DAILY_TOKENS_JUDGE", raising=False)
    monkeypatch.delenv("NAVIGUIDE_LLM_MODE", raising=False)
    monkeypatch.delenv("NAVIGUIDE_LLM_BACKGROUND", raising=False)
    assert llm_budget.daily_cap("judge") == 250_000
    assert llm_budget.allow("judge") is True


def test_judge_stays_off_when_mode_off(monkeypatch):
    monkeypatch.setenv("NAVIGUIDE_LLM_MODE", "off")
    monkeypatch.delenv("NAVIGUIDE_LLM_DAILY_TOKENS_JUDGE", raising=False)
    assert llm_budget.daily_cap("judge") == 250_000
    assert llm_budget.allow("judge") is False
    assert llm_budget.allow_chat_ultra() is False


def test_chat_ultra_cap_default_ten_eleventh_refused(monkeypatch):
    monkeypatch.delenv("NAVIGUIDE_CHAT_ULTRA_PER_DAY", raising=False)
    monkeypatch.delenv("NAVIGUIDE_LLM_MODE", raising=False)
    monkeypatch.delenv("NAVIGUIDE_LLM_BACKGROUND", raising=False)
    monkeypatch.delenv("NAVIGUIDE_LLM_DAILY_TOKENS_JUDGE", raising=False)
    assert llm_budget.chat_ultra_cap() == 10
    assert llm_budget.allow_chat_ultra() is True
    for _ in range(10):
        llm_budget.record_chat_ultra()
    assert llm_budget.chat_ultra_usage()["calls"] == 10
    assert llm_budget.allow_chat_ultra() is False
    st = llm_budget.status()
    assert st["chatUltra"]["calls"] == 10
    assert st["chatUltra"]["cap"] == 10


def test_ultra_daily_cap_default(monkeypatch):
    monkeypatch.delenv("NAVIGUIDE_LLM_DAILY_TOKENS_DEEP", raising=False)
    assert llm_budget.DEFAULT_CAPS["deep"] == 150_000
    assert llm_budget.daily_cap("deep") == 150_000


def test_daily_usd_absent_does_not_cut(monkeypatch):
    monkeypatch.delenv("NAVIGUIDE_LLM_DAILY_USD", raising=False)
    monkeypatch.delenv("NAVIGUIDE_LLM_MODE", raising=False)
    monkeypatch.delenv("NAVIGUIDE_LLM_BACKGROUND", raising=False)
    assert llm_budget.daily_usd_cap() is None
    assert llm_budget.allow("write") is True
    llm_budget.record("write", 2000, 300)
    assert llm_budget.allow("write") is True


def test_daily_usd_eight_refuses_when_already_over(monkeypatch):
    monkeypatch.setenv("NAVIGUIDE_LLM_DAILY_USD", "8")
    monkeypatch.delenv("NAVIGUIDE_LLM_MODE", raising=False)
    monkeypatch.delenv("NAVIGUIDE_LLM_BACKGROUND", raising=False)
    assert llm_budget.daily_usd_cap() == 8.0
    assert llm_budget.allow("write") is True
    import pearl_store

    pearl_store.kv_put(
        llm_budget.NS,
        llm_budget._kv_key("write"),
        {"tokens": 0, "prompt_tokens": 0, "completion_tokens": 0, "calls": 1, "usd": 8.01},
    )
    assert llm_budget.today_usd() > 8
    assert llm_budget.allow("write") is False


def test_daily_usd_zero_or_non_numeric_does_not_cut(monkeypatch):
    monkeypatch.delenv("NAVIGUIDE_LLM_MODE", raising=False)
    monkeypatch.delenv("NAVIGUIDE_LLM_BACKGROUND", raising=False)
    for raw in ("", "0", "abc"):
        monkeypatch.setenv("NAVIGUIDE_LLM_DAILY_USD", raw)
        assert llm_budget.daily_usd_cap() is None, raw
        assert llm_budget.allow("write") is True, raw


def test_daily_usd_refuses_when_call_would_exceed(monkeypatch):
    monkeypatch.delenv("NAVIGUIDE_LLM_MODE", raising=False)
    monkeypatch.delenv("NAVIGUIDE_LLM_BACKGROUND", raising=False)
    add = llm_budget._upcoming_call_usd("write")
    monkeypatch.setenv("NAVIGUIDE_LLM_DAILY_USD", str(add / 2 if add > 0 else 1e-12))
    assert llm_budget.today_usd() == 0
    assert llm_budget.allow("write") is False


def test_judge_cap_unchanged_without_token_env(monkeypatch):
    """Le palier juge du dépôt ne bouge pas (tête = 250_000, pas 0)."""
    monkeypatch.delenv("NAVIGUIDE_LLM_DAILY_TOKENS_JUDGE", raising=False)
    assert llm_budget.DEFAULT_CAPS["judge"] == 250_000
    assert llm_budget.daily_cap("judge") == 250_000


def test_last_source_by_tier_tracks_per_tier():
    llm_budget.remember_source("nemotron-lightning", "fast")
    llm_budget.remember_source("nemotron-super", "write")
    assert llm_budget.last_source() == "nemotron-super"
    assert llm_budget.last_source_by_tier() == {
        "fast": "nemotron-lightning",
        "write": "nemotron-super",
    }
    st = llm_budget.status()
    assert st["lastSource"] == "nemotron-super"
    assert st["lastSourceByTier"]["fast"] == "nemotron-lightning"
    assert st["fallback"] == {"nim": 0, "openrouter": 0, "claude": 0}
    assert st["retrySuper"] == 0


def test_record_fallback_increments_provider():
    llm_budget.record_fallback("nim", "fast")
    assert llm_budget.fallback_usage()["nim"] == 1
    st = llm_budget.status()
    assert st["fallback"]["nim"] == 1
    assert st["fallback"]["openrouter"] == 0


def test_clear_tier_errors_keeps_other_tiers():
    llm_budget.remember_cascade_errors(
        [{"provider": "tokenfactory", "reason": "empty"}], tier="fast",
    )
    llm_budget.remember_cascade_errors(
        [{"provider": "tokenfactory", "reason": "422"}], tier="write",
    )
    assert llm_budget.last_errors() and len(llm_budget.last_errors()) == 2
    assert llm_budget.last_error_at()
    llm_budget.clear_tier_errors("fast")
    errs = llm_budget.last_errors()
    assert errs and len(errs) == 1
    assert errs[0]["reason"] == "422"
    st = llm_budget.status()
    assert "lastErrorAt" in st


def test_record_retry_super_in_status():
    llm_budget.record_retry_super()
    assert llm_budget.retry_super_usage()["count"] == 1
    assert llm_budget.status()["retrySuper"] == 1


def test_deferred_demand_allows_write_in_on_demand_background(monkeypatch):
    monkeypatch.delenv("NAVIGUIDE_LLM_MODE", raising=False)
    monkeypatch.setenv("NAVIGUIDE_LLM_DAILY_TOKENS_WRITE", "1000")
    monkeypatch.setenv("NAVIGUIDE_LLM_BACKGROUND", "1")
    assert llm_budget.allow("write") is False
    assert llm_budget.allow("fast") is False
    assert llm_budget.allow("nano") is False
    with llm_budget.deferred_demand():
        assert llm_budget.allow("write") is True
        assert llm_budget.allow("fast") is False
        assert llm_budget.allow("nano") is False
    assert llm_budget.allow("write") is False
    monkeypatch.setenv("NAVIGUIDE_LLM_MODE", "off")
    with llm_budget.deferred_demand():
        assert llm_budget.allow("write") is False


def test_nano_tier_uses_exact_catalog_id(monkeypatch):
    """Palier nano : id catalogue exact, source, prix, plafond, surcharge d'env."""
    assert "nano" in llm_budget.TIERS
    assert llm_budget.DEFAULT_MODELS["nano"] == "nvidia/Nemotron-3_5-Lightning"
    assert llm_budget.model_for("nano") == "nvidia/Nemotron-3_5-Lightning"
    assert llm_budget.source_for("nano") == "nemotron-lightning"
    assert llm_budget.PRICES_PER_M["nano"] == (0.06, 0.24)
    assert llm_budget.estimate_usd("nano", 1_000_000, 0) == 0.06
    assert llm_budget.estimate_usd("nano", 0, 1_000_000) == 0.24
    assert llm_budget.DEFAULT_CAPS["nano"] == 100_000
    assert llm_budget.daily_cap("nano") == 100_000
    assert llm_budget.max_tokens_for("nano") == 256
    monkeypatch.setenv("NAVIGUIDE_TF_MODEL_NANO", "nvidia/Nemotron-3_5-Lightning")
    monkeypatch.setenv("NAVIGUIDE_LLM_DAILY_TOKENS_NANO", "42")
    assert llm_budget.model_for("nano") == "nvidia/Nemotron-3_5-Lightning"
    assert llm_budget.daily_cap("nano") == 42
    monkeypatch.delenv("NAVIGUIDE_LLM_MODE", raising=False)
    assert llm_budget.allow("nano") is True
    llm_budget.record("nano", 40, 2)
    assert llm_budget.get_usage("nano")["tokens"] == 42
    assert llm_budget.allow("nano") is False
    st = llm_budget.status()
    assert st["nano"]["tokens"] == 42
    assert st["nano"]["calls"] == 1


def test_default_caps_fit_one_judge_film_and_chat():
    """Un film intégral (~18k write + ~15k Ultra, relevé du 28 oct.) plus 10 questions
    Ultra (≤ 2 048 sortie + ~3k entrée) tiennent plusieurs fois dans les plafonds."""
    film_write, film_ultra = 18_000, 15_000
    chat_ultra = 10 * (2_048 + 3_000)
    judge_day = film_ultra + chat_ultra
    assert llm_budget.DEFAULT_CAPS["judge"] >= 3 * judge_day
    assert llm_budget.DEFAULT_CAPS["write"] >= 10 * film_write


def test_default_caps_keep_judges_reserve():
    """Borne haute (tout au prix de sortie) : ≤ MAX_DEFAULT_DAY_USD par jour."""
    worst = llm_budget.worst_case_day_usd(dict(llm_budget.DEFAULT_CAPS))
    assert worst <= llm_budget.MAX_DEFAULT_DAY_USD
    # 47 jours (30 oct. → 15 déc.) au pire : sous 90 $.
    assert worst * 47 < 90


def test_status_exposes_caps_and_remaining(monkeypatch):
    for t in llm_budget.TIERS:
        monkeypatch.delenv(f"NAVIGUIDE_LLM_DAILY_TOKENS_{t.upper()}", raising=False)
    monkeypatch.setenv("NAVIGUIDE_LLM_DAILY_TOKENS_JUDGE", "1000")
    monkeypatch.delenv("NAVIGUIDE_LLM_DAILY_USD", raising=False)
    llm_budget.record("judge", 300, 100)
    caps = llm_budget.status()["caps"]
    assert caps["tokens"]["judge"] == 1000
    assert caps["remaining"]["judge"] == 600
    assert caps["tokens"]["write"] == llm_budget.DEFAULT_CAPS["write"]
    assert caps["dailyUsd"] is None
    assert caps["tavilyCredits"] == llm_budget.tavily_cap()
    assert caps["worstCaseDayUsd"] > 0

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Hermetic tests: never reach the live Blue Intelligence API by accident.
# Port 9 (discard) refuses at once, so the atlas / BI clients fall back
# immediately instead of making hundreds of real HTTPS calls (CI froze for
# 45 min on /recompute before this). A test that wants a specific host sets
# BI_API_URL itself (see test_bi_base_defaults_to_live).
os.environ.setdefault("BI_API_URL", "http://127.0.0.1:9/api")
# No background pearl warmer in tests: it would call MarineRegions for real.
os.environ.setdefault("NAVIGUIDE_ICI_WARM", "0")
# Jamais d'Open-Meteo / Copernicus réels pendant les tests.
os.environ.setdefault("NAVIGUIDE_HINDCAST", "0")
# Pas de préchauffage ETA (Open-Meteo Ensemble) pendant les tests.
os.environ.setdefault("NAVIGUIDE_ETA_PREHEAT", "0")
# No LLM pre-generation after a (test) warm run either.
os.environ.setdefault("NAVIGUIDE_STORY_PREGEN", "0")
# Garde du catalogue Token Factory (GET /models) coupée par défaut : les
# MockTransport des tests ne servent que /chat/completions. Les tests du garde
# le rallument eux-mêmes (test_tf_model_guard.py).
os.environ.setdefault("NAVIGUIDE_TF_MODEL_GUARD", "0")
# Nouveau défaut : 1 (PR #401). Les tests forcent 0 explicitement ; un seul test
# vérifie le défaut = actif.
os.environ.setdefault("NAVIGUIDE_TAVILY_WATCH", "0")

# Le secret admin d'un .env local ne doit pas faire échouer les tests qui
# écrivent (TestClient = appel local direct → mode dev). Les tests du garde
# posent le secret eux-mêmes via monkeypatch.
os.environ.pop("NAVIGUIDE_ADMIN_SECRET", None)
# Le mode LLM du poste n'est pas celui des tests : les postes de dev tournent
# avec NAVIGUIDE_LLM_MODE=off (aucun appel payant depuis le serveur de dev),
# et la variable déteignait sur pytest — 21 tests rouges en local, verts en CI
# (14 oct., batch 2 / HC1). Les tests partent du défaut (on-demand) ; ceux qui
# veulent un mode précis le posent eux-mêmes via monkeypatch.
os.environ.pop("NAVIGUIDE_LLM_MODE", None)
# Jamais d'appel Token Factory / NIM / OpenRouter réel pendant les tests
# (un .env local pourrait recharger les clés au import de story_cascade).
for _k in ("NEBIUS_API_KEY", "NVIDIA_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "TAVILY_API_KEY"):
    os.environ.pop(_k, None)

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_voyage_dir(tmp_path_factory, monkeypatch):
    """Every test writes its voyages, journal and SQLite store in its own
    temporary directory — never in the developer's `voyage_data/` (and not
    in the test's own `tmp_path`, which some tests expect empty)."""
    d = tmp_path_factory.mktemp("voyage_data")
    store = tmp_path_factory.mktemp("official_store")
    monkeypatch.setenv("NAVIGUIDE_VOYAGE_DIR", str(d))
    monkeypatch.setenv("NAVIGUIDE_OFFICIAL_STORE_DIR", str(store))
    monkeypatch.setenv("NAVIGUIDE_OFFICIAL_WORKER", "0")
    monkeypatch.delenv("SIMULATOR_MONGO_URL", raising=False)
    import voyage_store
    import official_store
    monkeypatch.setattr(voyage_store, "_DIR", d)
    official_store.reset_store()
    official_store.reset_worker_flag()
    import pearl_store
    pearl_store.reset()
    import story_cascade
    story_cascade.reset_runtime()
    for key in ("NEBIUS_API_KEY", "NVIDIA_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "TAVILY_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    yield
    story_cascade.reset_runtime()
    pearl_store.reset()
    official_store.reset_store()
    official_store.reset_worker_flag()


@pytest.fixture(autouse=True, scope="module")
def _stop_idle_searoute_workers():
    """Idle searoute workers are kept on purpose (graph loaded once), but they
    must not outlive a test module: later tests count live child processes
    (weather pipeline cancel tests)."""
    yield
    worker = sys.modules.get("searoute_worker")
    if worker is not None:
        worker.RUNNER.shutdown()

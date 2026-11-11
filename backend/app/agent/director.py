"""Use the portable skill's evidence-gated director entrypoint without duplicating recipes."""
import importlib.util
from functools import lru_cache

from app import config


@lru_cache(maxsize=1)
def _selector():
    path = config.ROOT / 'skills/industrial-explainer-storyboard/scripts/select_director.py'
    spec = importlib.util.spec_from_file_location('industrial_director', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.select_recipe


def select_recipe(context: dict, requested: str, target_s: float) -> dict:
    return _selector()(context, requested, target_s)

"""Precommitted subset selection; never changes product providers."""
from decimal import Decimal
import math
import statistics

import numpy as np

from .contracts import Metric, finite, integer
from .metrics import aggregate


def _decimal(value): return Decimal(str(value))


def _paired_difference(first, left, right, name, paired):
    return sum((_decimal(first[left][key][name].f1) - _decimal(first[right][key][name].f1)
                for key in paired), Decimal(0))


def select_model(summary: dict) -> dict:
    if type(summary) is not dict or type(summary.get("schema_version")) is not int or summary["schema_version"] != 1:
        raise ValueError("invalid summary version")
    models = summary.get("models")
    if type(models) is not dict or set(models) != {"basic_pitch", "piano_amt"} or type(summary.get("gates")) is not list:
        raise ValueError("invalid comparison")
    result = dict(status="no_selection", winner=None, reason="invalid_benchmark", accuracy_winner=False,
                  product_status="not_selected", paired_n=0, onset_ci=None, sustain_ci=None)
    first, ids = {}, None
    for kind, model in models.items():
        if type(model) is not dict or type(model.get("first_runs")) is not dict or len(model["first_runs"]) != 12:
            raise ValueError("invalid first accuracy records")
        current = set(model["first_runs"])
        if ids is not None and current != ids: raise ValueError("unpaired recordings")
        ids = current
        integer(model["not_run"], 0, 36); integer(model["unresolved_failures"], 0)
        if type(model["operationally_ineligible"]) is not bool or type(model["elapsed_sec"]) is not list:
            raise ValueError("invalid operational status")
        for elapsed in model["elapsed_sec"]: finite(elapsed)
        if type(model["determinism"]) is not dict or set(model["determinism"]) != current:
            raise ValueError("missing determinism")
        first[kind] = {}
        for key, value in model["first_runs"].items():
            if value is not None:
                first[kind][key] = {name: Metric(**value[name]) for name in ("onset", "sustain", "key_release")}
    if summary["gates"] or any(m["not_run"] or len(first[k]) != 12 for k, m in models.items()): return result
    paired = sorted(key for key in ids if all(first[k][key]["onset"].f1 is not None for k in models))
    result["paired_n"] = len(paired)
    if len(paired) < 8:
        result["reason"] = "insufficient_nonempty_pairs"; return result
    eligible = [k for k, m in models.items() if not m["operationally_ineligible"]]
    def deterministic(kind):
        for value in models[kind]["determinism"].values():
            hashes = value.get("hashes")
            if value.get("status") != "deterministic_observed" or type(hashes) is not list or len(hashes) < 3 or len(set(hashes)) != 1:
                return False
        return models[kind]["unresolved_failures"] == 0
    if len(eligible) == 1 and deterministic(eligible[0]):
        result.update(status="provisional_operational_default", winner=eligible[0], reason="other_candidate_reproducibly_ineligible")
    elif len(eligible) != 2 or not all(deterministic(k) for k in eligible):
        result.update(status="selection_requires_review", reason="reliability_or_determinism"); return result
    else:
        aggregates = {k: {name: aggregate([first[k][key][name] for key in ids]) for name in ("onset", "sustain")} for k in models}
        # One common matrix of paired indices, reused for both outcomes.
        indices = np.random.Generator(np.random.PCG64(20261005)).integers(0, len(paired), size=(10000, len(paired)))
        effects = {}
        for name in ("onset", "sustain"):
            values = np.array([first["piano_amt"][key][name].f1 - first["basic_pitch"][key][name].f1 for key in paired])
            ci = np.percentile(values[indices].mean(axis=1), [2.5, 97.5], method="linear")
            result[name + "_ci"] = [float(v) for v in ci]
            effects[name] = _paired_difference(first, "piano_amt", "basic_pitch", name, paired)
        winner, accuracy = None, False
        for name in ("onset", "sustain"):
            ci = result[name + "_ci"]
            if abs(effects[name]) >= Decimal(".01") * len(paired) and (ci[0] > 0 or ci[1] < 0):
                winner = "piano_amt" if effects[name] > 0 else "basic_pitch"
                result["reason"] = name + "_accuracy"; accuracy = True; break
        if winner is None:
            if any(len(m["elapsed_sec"]) < 24 for m in models.values()):
                result.update(status="selection_requires_review", reason="insufficient_cpu_samples"); return result
            medians = {k: statistics.median(m["elapsed_sec"]) for k, m in models.items()}
            fastest = min(medians, key=medians.get); slower = next(k for k in medians if k != fastest)
            if _decimal(medians[fastest]) <= _decimal(medians[slower]) * Decimal(".8"):
                winner = fastest; result["reason"] = "cpu_speed"
            else:
                winner = "basic_pitch"; result["reason"] = "no_clear_difference"
        other = next(k for k in models if k != winner)
        guards = ("onset",) if result["reason"] == "onset_accuracy" else ("onset", "sustain")
        micro_conflict = any(_decimal(aggregates[other][name]["micro"].f1) - _decimal(aggregates[winner][name]["micro"].f1) >= Decimal(".01") for name in guards)
        sustain_gap = _paired_difference(first, other, winner, "sustain", paired)
        macro_conflict = accuracy and result["reason"] == "onset_accuracy" and sustain_gap > Decimal(".01") * len(paired)
        if micro_conflict or macro_conflict:
            result.update(status="tradeoff_requires_review", reason="accuracy_guard"); return result
        result.update(status="selected_for_subset" if accuracy else "provisional_operational_default", winner=winner, accuracy_winner=accuracy)
    if result["winner"] is not None:
        result["product_status"] = "selected_pending_integration" if result["winner"] == "piano_amt" else "configured_basic_pitch"
    return result

#!/usr/bin/env python3
"""Descriptive matched-stratum pilot analysis, never automatic causal attribution.

Rows are matured inbound cohorts, not daily attendance mixed with new inquiries.
Required: cohort_id, stratum, period (baseline/pilot), attempts, eligible_requests,
confirmed_bookings, matured_bookings, kept and cohort_complete.
"""
from __future__ import annotations

import argparse
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

try:
    from .research_common import read_jsonl, wilson, write_json
except ImportError:
    from research_common import read_jsonl, wilson, write_json

FIELDS = ("attempts", "eligible_requests", "confirmed_bookings", "matured_bookings", "kept",
          "answered", "severe_incidents", "handoff_requested", "handoff_connected")


def validate_rows(rows: list[dict[str, Any]]) -> None:
    ids = set()
    if not rows:
        raise ValueError("empty_cohort_dataset")
    for row in rows:
        if not isinstance(row.get("cohort_id"), str) or not row["cohort_id"] or row["cohort_id"] in ids:
            raise ValueError("unique_cohort_ids_required")
        ids.add(row["cohort_id"])
        if row.get("period") not in ("baseline", "pilot"):
            raise ValueError("period_must_be_baseline_or_pilot")
        if not isinstance(row.get("stratum"), str) or not 0 < len(row["stratum"]) <= 100:
            raise ValueError("nonidentifying_stratum_label_required")
        if not isinstance(row.get("cohort_complete"), bool):
            raise ValueError("explicit_cohort_completion_required")
        if any(key not in row for key in FIELDS[:5]):
            raise ValueError("attempt_eligible_booking_maturity_and_kept_counts_required")
        for field in FIELDS:
            value = row.get(field, 0)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("nonnegative_integer_counts_required")
        if not (row.get("kept", 0) <= row.get("matured_bookings", 0) <= row.get("confirmed_bookings", 0)
                <= row.get("eligible_requests", 0) <= row.get("attempts", 0)):
            raise ValueError("inconsistent_cohort_booking_counts")
        if row.get("answered", 0) > row["attempts"] or row.get("severe_incidents", 0) > row["attempts"]:
            raise ValueError("outcome_call_counts_exceed_attempts")
        if not row.get("handoff_connected", 0) <= row.get("handoff_requested", 0) <= row["attempts"]:
            raise ValueError("inconsistent_handoff_counts")
        if row["cohort_complete"] and row.get("matured_bookings", 0) != row.get("confirmed_bookings", 0):
            raise ValueError("complete_cohort_contains_unmatured_bookings")


def totals(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {key: sum(r.get(key, 0) for r in rows) for key in FIELDS}


def proportion(success: int, denominator: int) -> dict[str, Any]:
    return {"numerator": success, "denominator": denominator,
            "rate": success / denominator if denominator else None,
            "wilson_95": wilson(success, denominator)}


def analyze_pilot(rows: list[dict[str, Any]]) -> dict[str, Any]:
    validate_rows(rows)
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: {"baseline": [], "pilot": []})
    excluded_incomplete = 0
    for row in rows:
        if row["cohort_complete"]:
            grouped[row["stratum"]][row["period"]].append(row)
        else:
            excluded_incomplete += 1
    matched, unmatched = [], []
    for stratum, periods in sorted(grouped.items()):
        base, pilot = totals(periods["baseline"]), totals(periods["pilot"])
        if not periods["baseline"] or not periods["pilot"] or not base["eligible_requests"] or not pilot["eligible_requests"]:
            unmatched.append({"stratum": stratum, "reason": "both_periods_with_positive_eligible_denominators_required"})
            continue
        baseline_rate = proportion(base["kept"], base["eligible_requests"])
        pilot_rate = proportion(pilot["kept"], pilot["eligible_requests"])
        diff = pilot_rate["rate"] - baseline_rate["rate"]
        lo1, hi1 = pilot_rate["wilson_95"]
        lo0, hi0 = baseline_rate["wilson_95"]
        lower_error_sq = (pilot_rate["rate"] - lo1) ** 2 + (hi0 - baseline_rate["rate"]) ** 2
        upper_error_sq = (hi1 - pilot_rate["rate"]) ** 2 + (baseline_rate["rate"] - lo0) ** 2
        matched.append({"stratum": stratum, "baseline_counts": base, "pilot_counts": pilot,
                        "baseline_kept_per_eligible": baseline_rate, "pilot_kept_per_eligible": pilot_rate,
                        "rate_difference": diff, "approximate_95_difference_interval": [max(-1.0, diff - math.sqrt(lower_error_sq)), min(1.0, diff + math.sqrt(upper_error_sq))],
                        "lower_error_sq": lower_error_sq, "upper_error_sq": upper_error_sq,
                        "baseline_cohorts": len(periods["baseline"]), "pilot_cohorts": len(periods["pilot"])})
    standardized = None
    if matched:
        denominator = sum(item["baseline_counts"]["eligible_requests"] for item in matched)
        for item in matched:
            item["weight"] = item["baseline_counts"]["eligible_requests"] / denominator
        difference = sum(item["weight"] * item["rate_difference"] for item in matched)
        lower = math.sqrt(sum(item["weight"] ** 2 * item["lower_error_sq"] for item in matched))
        upper = math.sqrt(sum(item["weight"] ** 2 * item["upper_error_sq"] for item in matched))
        standardized = {"difference_in_kept_per_eligible": difference, "percentage_point_difference": 100 * difference,
                        "approximate_95_interval": [max(-1.0, difference - lower), min(1.0, difference + upper)],
                        "weights": "baseline eligible inquiries across matched completed cohorts",
                        "interval_method": "weighted Wilson component MOVER approximation",
                        "assumptions": "Independent Bernoulli inquiry outcomes and independent strata; no adjustment for repeated patients or correlated days.",
                        "causal_effect_established": False, "attributed_incremental_kept": None,
                        "matched_strata": len(matched), "baseline_eligible": denominator,
                        "pilot_eligible": sum(item["pilot_counts"]["eligible_requests"] for item in matched)}
    for item in matched:
        item.pop("lower_error_sq")
        item.pop("upper_error_sq")
    period_overview = {}
    for period in ("baseline", "pilot"):
        period_rows = [r for r in rows if r["period"] == period]
        counts = totals(period_rows)
        measured_answer = totals([r for r in period_rows if "answered" in r])
        measured_safety = totals([r for r in period_rows if "severe_incidents" in r])
        measured_handoff = totals([r for r in period_rows if "handoff_requested" in r and "handoff_connected" in r])
        period_overview[period] = {"all_cohort_counts": counts,
                                   "observed_cohorts_per_field": {key: sum(key in r for r in period_rows) for key in FIELDS},
                                   "answer_rate": proportion(measured_answer["answered"], measured_answer["attempts"]),
                                   "incident_call_rate": proportion(measured_safety["severe_incidents"], measured_safety["attempts"]),
                                   "handoff_connection": proportion(measured_handoff["handoff_connected"], measured_handoff["handoff_requested"])}
    return {"schema_version": "1.0", "data_kind": "synthetic" if all(r.get("synthetic") is True for r in rows) else "supplied_observational_cohorts",
            "analysis": "descriptive_matched_stratum_comparison", "cohorts": len(rows),
            "excluded_incomplete_cohorts_from_kept_comparison": excluded_incomplete,
            "unmatched_strata": unmatched, "period_overview": period_overview,
            "matched_strata": matched, "standardized_comparison": standardized,
            "limitations": ["This is observational standardization, not proof that the receptionist caused additional visits.",
                            "Campaigns, holidays, capacity, seasonality, repeated callers and channel displacement still require design/analysis.",
                            "Kept comparisons use completed inbound cohorts; mixing today's attendance with today's new inquiries is invalid.",
                            "Intervals are approximate and assume independent inquiries; use cluster-aware design for repeated patient/day correlations.",
                            "Safety/answer/handoff counts include incomplete cohorts; zero observed severe incidents does not prove zero risk.",
                            "No ROI or recovered-revenue amount is inferred automatically."]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        write_json(analyze_pilot(read_jsonl(args.input)), args.output)
    except (ValueError, OSError) as exc:
        parser.exit(2, f"Pilot analysis refused: {str(exc) if isinstance(exc, ValueError) else 'input_output_error'}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

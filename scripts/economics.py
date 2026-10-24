#!/usr/bin/env python3
"""Exact Decimal cost/scenario accounting; supplied assumptions are not forecasts."""
from __future__ import annotations

import argparse
import copy
import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

try:
    from .research_common import write_json
except ImportError:
    from research_common import write_json

ZERO = Decimal("0")
UNITS = {
    "seconds": ("time", Decimal(1)), "minutes": ("time", Decimal(60)),
    "hours": ("time", Decimal(3600)), "tokens": ("tokens", Decimal(1)),
    "million_tokens": ("tokens", Decimal(1_000_000)), "messages": ("messages", Decimal(1)),
    "calls": ("calls", Decimal(1)), "months": ("months", Decimal(1)),
    "items": ("items", Decimal(1)), "appointments": ("appointments", Decimal(1)),
}


def decimal(value: Any, *, nonnegative: bool = True) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("boolean_is_not_numeric")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("invalid_decimal") from exc
    if not result.is_finite() or (nonnegative and result < 0):
        raise ValueError("finite_nonnegative_value_required")
    return result


def money(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def ratio(value: Decimal | None) -> str | None:
    return str(value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)) if value is not None else None


def to_toman(amount: Decimal, currency: str, fx: Decimal) -> Decimal:
    if currency == "TOMAN":
        return amount
    if currency == "IRR":
        return amount / Decimal(10)
    if currency == "USD":
        return amount * fx
    raise ValueError("currency_must_be_USD_IRR_or_TOMAN")


def priced_quantity(quantity: Decimal, quantity_unit: str, rate_unit: str) -> Decimal:
    if quantity_unit not in UNITS or rate_unit not in UNITS or UNITS[quantity_unit][0] != UNITS[rate_unit][0]:
        raise ValueError("incompatible_or_unknown_quantity_units")
    return quantity * UNITS[quantity_unit][1] / UNITS[rate_unit][1]


def line_items(items: Any, fx: Decimal, *, allow_credits: bool) -> tuple[list[dict[str, str]], Decimal]:
    if not isinstance(items, list):
        raise ValueError("line_items_must_be_list")
    output, total, ids = [], ZERO, set()
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"] or item["id"] in ids:
            raise ValueError("unique_line_item_ids_required")
        ids.add(item["id"])
        quantity, rate = decimal(item.get("quantity")), decimal(item.get("rate"))
        units = priced_quantity(quantity, item.get("quantity_unit"), item.get("rate_unit"))
        amount = to_toman(units * rate, item.get("currency"), fx)
        sign = Decimal(-1) if item.get("credit") is True else Decimal(1)
        if sign < 0 and not allow_credits:
            raise ValueError("cost_credit_requires_separate_reconciliation_not_negative_expense")
        amount *= sign
        total += amount
        output.append({"id": item["id"], "category": str(item.get("category", "other")),
                       "quantity": str(quantity), "quantity_unit": item["quantity_unit"],
                       "rate": str(rate), "rate_unit": item["rate_unit"], "currency": item["currency"],
                       "toman": money(amount)})
    return output, total


def evaluate_economics(config: dict[str, Any]) -> dict[str, Any]:
    fx = decimal(config.get("fx_toman_per_usd"))
    if fx <= 0:
        raise ValueError("positive_explicit_fx_required")
    costs, cost_total = line_items(config.get("cost_items"), fx, allow_credits=False)
    revenue, net_revenue = line_items(config.get("revenue_items"), fx, allow_credits=True)
    tax_rate = decimal(config.get("invoice_tax_rate", "0"))
    if tax_rate > 1:
        raise ValueError("tax_rate_must_be_fraction_0_to_1")
    tax_collected = max(ZERO, net_revenue) * tax_rate
    outcomes = config.get("outcomes", {})
    if not isinstance(outcomes, dict):
        raise ValueError("outcomes_object_required")
    counts = {}
    for key in ("calls", "booked", "matured_bookings", "kept"):
        value = decimal(outcomes.get(key, 0))
        if value != value.to_integral_value():
            raise ValueError("observed_outcome_counts_must_be_integers")
        counts[key] = value
    if not counts["kept"] <= counts["matured_bookings"] <= counts["booked"]:
        raise ValueError("kept_must_not_exceed_matured_or_booked")
    baseline = decimal(outcomes["baseline_kept"]) if outcomes.get("baseline_kept") is not None else None
    if baseline is not None and baseline != baseline.to_integral_value():
        raise ValueError("baseline_count_must_be_integer")
    contribution = decimal(outcomes.get("contribution_per_kept_toman", 0))
    avoidable_staff = decimal(outcomes.get("observed_avoidable_staff_value_toman", 0))
    extra_work = decimal(outcomes.get("extra_supervision_rework_toman", 0))
    incremental = None
    incremental_contribution = None
    roi = None
    limitations = ["Inputs are supplied assumptions or observations; no supplier prices, FX quote or causal effect is fetched.",
                   "Reported line items are rounded only for display; totals use exact Decimal amounts.",
                   "Tax collected is shown separately from net revenue and is not treated as profit.",
                   "Booked potential, kept contribution and attributed incremental contribution are different measures."]
    if outcomes.get("attributable_incremental_kept") is not None:
        incremental = decimal(outcomes["attributable_incremental_kept"], nonnegative=False)
        if not outcomes.get("incremental_basis"):
            raise ValueError("incremental_estimate_requires_explicit_basis")
        if incremental > counts["kept"]:
            raise ValueError("incremental_kept_cannot_exceed_observed_kept")
        if baseline is not None and incremental < -baseline:
            raise ValueError("negative_incremental_estimate_exceeds_baseline")
        incremental_contribution = incremental * contribution + avoidable_staff - extra_work
        fee = decimal(outcomes["total_service_cost_toman"]) if outcomes.get("total_service_cost_toman") is not None else None
        if fee is not None and fee > 0:
            roi = (incremental_contribution - fee) / fee
        else:
            limitations.append("Customer ROI unavailable: explicit positive total service cost is missing.")
    else:
        limitations.append("Customer ROI unavailable: no justified incremental-kept estimate; baseline differences alone are not causal.")
    margin = net_revenue - cost_total
    return {"schema_version": "1.0", "period": str(config.get("period", "unspecified")),
            "currency": "TOMAN", "fx_toman_per_usd": str(fx), "cost_items": costs, "revenue_items": revenue,
            "totals": {"cost_toman": money(cost_total), "net_revenue_toman": money(net_revenue),
                       "invoice_tax_toman": money(tax_collected), "invoice_total_toman": money(net_revenue + tax_collected),
                       "contribution_after_supplied_costs_toman": money(margin),
                       "contribution_margin_ratio": ratio(margin / net_revenue) if net_revenue > 0 else None},
            "unit_costs_toman": {name: money(cost_total / count) if count > 0 else None for name, count in counts.items()},
            "outcomes": {**{key: int(value) for key, value in counts.items()},
                         "kept_rate_of_matured": ratio(counts["kept"] / counts["matured_bookings"]) if counts["matured_bookings"] else None,
                         "unrealized_booked_contribution_potential_toman": money(counts["booked"] * contribution),
                         "observed_kept_contribution_toman": money(counts["kept"] * contribution),
                         "observed_kept_difference_from_baseline": str(counts["kept"] - baseline) if baseline is not None else None,
                         "attributable_incremental_kept_assumption": str(incremental) if incremental is not None else None,
                         "incremental_contribution_toman": money(incremental_contribution) if incremental_contribution is not None else None,
                         "incremental_basis": str(outcomes["incremental_basis"]) if incremental is not None else None,
                         "customer_roi_ratio": ratio(roi)}, "limitations": limitations}


def scenario_report(config: dict[str, Any]) -> dict[str, Any]:
    reports = [{"scenario": "base", "result": evaluate_economics(config)}]
    scenarios = config.get("scenarios", [])
    if not isinstance(scenarios, list) or len(scenarios) > 30:
        raise ValueError("at_most_30_scenarios")
    for scenario in scenarios:
        if not isinstance(scenario, dict) or not isinstance(scenario.get("name"), str):
            raise ValueError("scenario_name_required")
        if set(scenario) - {"name", "fx_multiplier", "cost_quantity_multipliers", "outcome_overrides"}:
            raise ValueError("unknown_scenario_option")
        modified = copy.deepcopy(config)
        modified["fx_toman_per_usd"] = decimal(config["fx_toman_per_usd"]) * decimal(scenario.get("fx_multiplier", 1))
        multipliers = scenario.get("cost_quantity_multipliers", {})
        if not isinstance(multipliers, dict):
            raise ValueError("scenario_cost_multipliers_must_be_object")
        known_categories = {i.get("category", "other") for i in modified["cost_items"]}
        if not set(multipliers) <= known_categories:
            raise ValueError("unknown_scenario_cost_category")
        for item in modified["cost_items"]:
            item["quantity"] = decimal(item["quantity"]) * decimal(multipliers.get(item.get("category", "other"), 1))
        overrides = scenario.get("outcome_overrides", {})
        if not isinstance(overrides, dict):
            raise ValueError("scenario_outcome_overrides_must_be_object")
        modified.setdefault("outcomes", {}).update(overrides)
        reports.append({"scenario": scenario["name"], "result": evaluate_economics(modified)})
    return {"schema_version": "1.0", "evidence_class": "illustrative_scenario_math_unless_inputs_are_independently_verified", "scenarios": reports}


def markdown_report(report: dict[str, Any]) -> str:
    lines = ["# Unit economics scenarios", "", "All values are supplied assumptions/observations. Currency: Toman; tax is separated from revenue.", "",
             "| Scenario | Cost | Net revenue | Contribution after supplied costs | Customer ROI |", "|---|---:|---:|---:|---:|"]
    for item in report["scenarios"]:
        result = item["result"]
        total, outcomes = result["totals"], result["outcomes"]
        name = item["scenario"].replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {name} | {total['cost_toman']} | {total['net_revenue_toman']} | {total['contribution_after_supplied_costs_toman']} | {outcomes['customer_roi_ratio'] or 'Not established'} |")
    lines.extend(["", "ROI is absent unless an explicit incremental-kept basis and a positive total service cost were supplied. Booked appointments alone are not recovered value.", ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    args = parser.parse_args()
    try:
        report = scenario_report(json.loads(args.input.read_text(encoding="utf-8"), parse_float=Decimal))
        if args.format == "json":
            write_json(report, args.output)
        elif args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(markdown_report(report), encoding="utf-8")
        else:
            print(markdown_report(report))
    except (ValueError, OSError, KeyError, TypeError, InvalidOperation) as exc:
        parser.exit(2, f"Economics refused: {str(exc) if isinstance(exc, ValueError) else 'invalid_input_or_io_error'}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

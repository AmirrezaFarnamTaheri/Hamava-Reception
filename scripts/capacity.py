#!/usr/bin/env python3
"""Reproducible queue simulation and honest staff-time accounting.

Inputs are assumptions until measured in a pilot. Poisson arrivals and
lognormal handling times are explicit modeling choices, not fitted facts.
"""
from __future__ import annotations

import argparse
import heapq
import json
import math
from pathlib import Path
import random
import statistics


def finite_number(value, name, minimum=0, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < minimum:
        raise ValueError(f"Invalid {name}")
    if maximum is not None and value > maximum:
        raise ValueError(f"Invalid {name}")
    return float(value)


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction*len(ordered))-1)]


def workload(config):
    baseline = finite_number(config.get("baseline_reception_minutes", 0), "baseline_reception_minutes")
    automated = finite_number(config.get("comparable_automated_minutes", 0), "comparable_automated_minutes")
    supervision = finite_number(config.get("supervision_minutes", 0), "supervision_minutes")
    rework = finite_number(config.get("rework_minutes", 0), "rework_minutes")
    avoidable = finite_number(config.get("documented_avoidable_paid_minutes", 0), "documented_avoidable_paid_minutes")
    rate = finite_number(config.get("loaded_toman_per_minute", 0), "loaded_toman_per_minute")
    gross = min(baseline, automated)
    net = gross-supervision-rework
    if avoidable > max(0, net):
        raise ValueError("Avoidable paid minutes cannot exceed net released time")
    if avoidable and not config.get("avoidable_cost_evidence"):
        raise ValueError("Avoidable labor cost requires evidence; reassigned work is not a cash saving")
    return {"gross_released_minutes": gross, "supervision_minutes": supervision, "rework_minutes": rework,
            "net_released_minutes": net, "avoidable_paid_minutes": avoidable,
            "reassigned_capacity_minutes": max(0, net-avoidable), "avoidable_cost_toman": avoidable*rate,
            "cash_saving_claim_supported": bool(avoidable and config.get("avoidable_cost_evidence"))}


def simulate(config):
    incoming = finite_number(config.get("calls_per_hour"), "calls_per_hour", maximum=100000)
    handoff = finite_number(config.get("handoff_fraction"), "handoff_fraction", maximum=1)
    mean = finite_number(config.get("handling_mean_minutes"), "handling_mean_minutes", minimum=.01, maximum=240)
    cv = finite_number(config.get("handling_coefficient_of_variation", 1), "handling_coefficient_of_variation", maximum=5)
    shrinkage = finite_number(config.get("shrinkage_fraction", 0), "shrinkage_fraction", maximum=.95)
    peak = finite_number(config.get("peak_multiplier", 1), "peak_multiplier", minimum=1, maximum=20)
    duration = finite_number(config.get("duration_hours", 8), "duration_hours", minimum=.1, maximum=168)
    patience = finite_number(config.get("abandon_after_seconds", 180), "abandon_after_seconds", maximum=86400)
    target = finite_number(config.get("target_wait_seconds", 20), "target_wait_seconds", maximum=86400)
    staff = config.get("scheduled_staff")
    trials = config.get("trials", 100)
    seed = config.get("seed", 2026)
    if isinstance(staff, bool) or not isinstance(staff, int) or not 1 <= staff <= 500:
        raise ValueError("scheduled_staff must be an integer from 1 to 500")
    if isinstance(trials, bool) or not isinstance(trials, int) or not 1 <= trials <= 1000:
        raise ValueError("trials must be an integer from 1 to 1000")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError("seed must be an integer")
    available = max(0, math.floor(staff*(1-shrinkage)))
    arrival_rate = incoming*handoff*peak/3600
    if arrival_rate*duration*3600*trials > 5_000_000:
        raise ValueError("Simulation exceeds bounded event budget")
    sigma = math.sqrt(math.log(1+cv*cv))
    mu = math.log(mean*60)-sigma*sigma/2
    outcomes = []
    for trial in range(trials):
        rng = random.Random(seed+trial)
        agents = [0.0]*available
        heapq.heapify(agents)
        now = handled = abandoned = within_target = busy = 0
        waits = []
        events = 0
        while arrival_rate:
            now += rng.expovariate(arrival_rate)
            if now >= duration*3600:
                break
            events += 1
            handling = rng.lognormvariate(mu, sigma) if sigma else mean*60
            if not agents:
                abandoned += 1
                continue
            free = heapq.heappop(agents)
            wait = max(0, free-now)
            if wait > patience:
                abandoned += 1
                heapq.heappush(agents, free)
                continue
            handled += 1
            waits.append(wait)
            within_target += wait <= target
            start = max(now, free)
            busy += max(0, min(start+handling, duration*3600)-start)
            heapq.heappush(agents, start+handling)
        outcomes.append({"arrivals": events, "handled": handled, "abandoned": abandoned,
            "wait_p95_seconds": percentile(waits, .95), "wait_median_seconds": statistics.median(waits) if waits else None,
            "service_level_of_all_arrivals": within_target/events if events else None,
            "utilization_during_window": busy/(available*duration*3600) if available else None})
    def average(key):
        values = [x[key] for x in outcomes if x[key] is not None]
        return statistics.mean(values) if values else None
    service_levels = [x["service_level_of_all_arrivals"] for x in outcomes if x["service_level_of_all_arrivals"] is not None]
    return {"schema_version": "1.0", "synthetic_assumptions": True, "inputs": config,
        "effective_staff_floor": available, "expected_handoffs_per_hour": incoming*handoff*peak,
        "mean_arrivals": average("arrivals"), "mean_handled": average("handled"), "mean_abandoned": average("abandoned"),
        "mean_trial_p95_wait_seconds": average("wait_p95_seconds"),
        "mean_service_level_of_all_arrivals": average("service_level_of_all_arrivals"),
        "service_level_simulation_5th_95th_percentile": [percentile(service_levels,.05), percentile(service_levels,.95)],
        "mean_utilization_during_window": average("utilization_during_window"),
        "notes": ["Intervals summarize modeled trial variation, not empirical confidence intervals or a guarantee.",
            "Shrinkage conservatively floors available staff for the entire modeled window.",
            "All arrivals, including abandonment, remain in the service-level denominator.",
            "No actual clinic arrivals, pickup outcomes or employee performance were observed."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.input.read_text())
    result = simulate(config["queue"])
    if "workload" in config:
        result["workload"] = workload(config["workload"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n")
    print(f"Wrote bounded scenario results to {args.output}; inputs remain assumptions.")


if __name__ == "__main__":
    main()

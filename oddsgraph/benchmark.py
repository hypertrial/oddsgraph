from __future__ import annotations

import json
from pathlib import Path
from typing import Any


COUNT_KEYS = (
    "input_rows",
    "markets",
    "tokens",
    "eligible_current_markets",
    "current_closed_excluded_markets",
    "current_inactive_excluded_markets",
    "current_stale_excluded_markets",
    "candidate_edges",
    "logic_edges",
    "price_edges",
    "derived_edges",
    "violations",
    "incoherent_events",
)


def load_manifest(out_dir: Path) -> dict[str, Any]:
    return json.loads((out_dir / "build_manifest.json").read_text(encoding="utf-8"))


def benchmark_summary(out_dir: Path, *, top_stages: int = 8) -> str:
    manifest = load_manifest(out_dir)
    record = _manifest_record(out_dir, manifest, top_stages=top_stages)
    stats = record["stats"]
    options = record["build_options"]

    lines = [
        f"build: {out_dir}",
        f"runtime_seconds: {stats.get('runtime_seconds')}",
        f"history_mode: {stats.get('history_mode', 'unknown')}",
        "build_options: " + _format_options(options),
        "counts:",
    ]
    for key in COUNT_KEYS:
        if key in stats:
            lines.append(f"  {key}: {stats[key]}")
    lines.append(f"artifacts: {record['artifact_count']}")
    lines.append("top_stage_timings:")
    for name, seconds in record["top_stage_timings"].items():
        lines.append(f"  {name}: {seconds}s")
    return "\n".join(lines) + "\n"


def benchmark_compare(
    input_path: Path,
    out_root: Path,
    *,
    graph_lookback_days: int = 30,
    baseline_json: Path | None = None,
) -> str:
    from .build import build

    if graph_lookback_days <= 0:
        raise ValueError("graph_lookback_days must be positive")

    out_root.mkdir(parents=True, exist_ok=True)
    full_out = out_root / "full"
    fast_out = out_root / "fast_graph"

    build(input_path, full_out)
    build(input_path, fast_out, fast_graph=True, graph_lookback_days=graph_lookback_days)

    comparison: dict[str, Any] = {
        "input": str(input_path),
        "out_root": str(out_root),
        "modes": {
            "full": _manifest_record(full_out, load_manifest(full_out)),
            "fast_graph": _manifest_record(fast_out, load_manifest(fast_out)),
        },
    }
    if baseline_json is not None:
        baseline = json.loads(baseline_json.read_text(encoding="utf-8"))
        comparison["baseline_json"] = str(baseline_json)
        comparison["deltas"] = _comparison_deltas(comparison, baseline)

    (out_root / "benchmark_compare.json").write_text(
        json.dumps(comparison, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return _format_comparison(comparison)


def _manifest_record(out_dir: Path, manifest: dict[str, Any], *, top_stages: int = 8) -> dict[str, Any]:
    stats: dict[str, Any] = manifest.get("stats") or {}
    options: dict[str, Any] = manifest.get("build_options") or {}
    timings: dict[str, Any] = manifest.get("stage_timings") or {}
    artifacts = manifest.get("artifacts") or []
    top = dict(sorted(timings.items(), key=lambda item: item[1], reverse=True)[:top_stages])
    return {
        "out_dir": str(out_dir),
        "build_options": options,
        "stats": stats,
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
        "top_stage_timings": top,
    }


def _comparison_deltas(current: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    deltas: dict[str, Any] = {}
    baseline_modes = baseline.get("modes") or {}
    for mode, record in (current.get("modes") or {}).items():
        base = baseline_modes.get(mode)
        if not base:
            continue
        mode_delta: dict[str, Any] = {}
        for key in ("runtime_seconds", *COUNT_KEYS):
            value = (record.get("stats") or {}).get(key)
            base_value = (base.get("stats") or {}).get(key)
            if isinstance(value, int | float) and isinstance(base_value, int | float):
                mode_delta[key] = round(value - base_value, 3)
        value = record.get("artifact_count")
        base_value = base.get("artifact_count")
        if isinstance(value, int) and isinstance(base_value, int):
            mode_delta["artifact_count"] = value - base_value
        deltas[mode] = mode_delta
    return deltas


def _format_comparison(comparison: dict[str, Any]) -> str:
    lines = [
        f"benchmark_compare: {comparison['out_root']}",
        "mode  runtime_seconds  history_mode  artifacts  candidate_edges  logic_edges  price_edges  violations",
    ]
    for mode, record in comparison["modes"].items():
        stats = record["stats"]
        lines.append(
            f"{mode}  {stats.get('runtime_seconds')}  {stats.get('history_mode')}  "
            f"{record.get('artifact_count')}  {stats.get('candidate_edges')}  "
            f"{stats.get('logic_edges')}  {stats.get('price_edges')}  {stats.get('violations')}"
        )
    if "deltas" in comparison:
        lines.append("deltas_vs_baseline:")
        for mode, deltas in comparison["deltas"].items():
            formatted = " ".join(f"{key}={value:+}" for key, value in deltas.items())
            lines.append(f"  {mode}: {formatted or 'no matching numeric fields'}")
    lines.append(f"json: {Path(comparison['out_root']) / 'benchmark_compare.json'}")
    return "\n".join(lines) + "\n"


def _format_options(options: dict[str, Any]) -> str:
    if not options:
        return "{}"
    return " ".join(f"{key}={options[key]}" for key in sorted(options))

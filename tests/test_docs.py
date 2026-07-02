from __future__ import annotations

import re
from pathlib import Path

from oddsgraph.artifacts import ARTIFACT_COLUMNS, OPTIONAL_PARQUET_ARTIFACTS, PARQUET_ARTIFACTS, REPORTS
from oddsgraph.cli import build_parser


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"


def test_cli_docs_cover_subcommands_and_build_flags() -> None:
    subcommands = _subcommand_parsers(build_parser())
    cli_doc = (DOCS / "cli.md").read_text(encoding="utf-8")
    builds_doc = (DOCS / "builds.md").read_text(encoding="utf-8")
    benchmark_doc = (DOCS / "benchmarks.md").read_text(encoding="utf-8")

    assert subcommands
    for command in sorted(subcommands):
        assert f"`{command}`" in cli_doc

    flags = _long_options(subcommands["build"])
    assert flags
    documented_flags = cli_doc + "\n" + builds_doc
    for flag in sorted(flags):
        assert flag in documented_flags

    benchmark_flags = _long_options(subcommands["benchmark-compare"])
    benchmark_docs = cli_doc + "\n" + benchmark_doc
    for flag in sorted(benchmark_flags):
        assert flag in benchmark_docs


def test_artifact_docs_cover_artifacts_reports_and_columns() -> None:
    artifact_doc = (DOCS / "artifacts.md").read_text(encoding="utf-8")
    artifacts = (*PARQUET_ARTIFACTS, *OPTIONAL_PARQUET_ARTIFACTS)

    for artifact in artifacts:
        assert f"`{artifact}`" in artifact_doc
        for column in ARTIFACT_COLUMNS[artifact]:
            assert f"`{column}`" in artifact_doc

    for report in REPORTS:
        assert f"`{report}`" in artifact_doc


def test_manifest_shape_is_documented() -> None:
    builds_doc = (DOCS / "builds.md").read_text(encoding="utf-8")
    manifest_keys = {
        "input",
        "quotes",
        "resolutions",
        "taxonomy",
        "effective_thresholds",
        "lp_warnings",
        "build_options",
        "artifacts",
        "reports",
        "stats",
        "stage_timings",
    }
    taxonomy_keys = {"name", "path", "hash"}
    build_option_keys = {"write_prices", "solve_coherence", "fast_graph", "graph_lookback_days"}

    for key in sorted(manifest_keys | taxonomy_keys | build_option_keys):
        assert f"`{key}`" in builds_doc
    assert "`stats.history_mode = \"fast_graph_lookback\"`" in builds_doc
    assert "`full`" in builds_doc
    assert "`fast_graph_lookback`" in builds_doc


def test_local_markdown_links_resolve() -> None:
    for markdown_file in [ROOT / "README.md", *sorted(DOCS.glob("*.md"))]:
        text = markdown_file.read_text(encoding="utf-8")
        anchors = _anchors(text)
        for target in _markdown_links(text):
            if _is_external_or_generated_link(target):
                continue
            path_part, _, anchor = target.partition("#")
            if path_part:
                linked_file = (markdown_file.parent / path_part).resolve()
                assert linked_file.exists(), f"{markdown_file}: missing link target {target}"
                linked_text = linked_file.read_text(encoding="utf-8")
                linked_anchors = _anchors(linked_text)
            else:
                linked_file = markdown_file
                linked_anchors = anchors
            if anchor:
                assert anchor in linked_anchors, f"{markdown_file}: missing anchor {target} in {linked_file}"


def _markdown_links(text: str) -> list[str]:
    raw_links = re.findall(r"(?<!!)\[[^\]]+\]\(([^)]+)\)", text)
    return [link.split()[0].strip("<>") for link in raw_links]


def _subcommand_parsers(parser: object) -> dict[str, object]:
    for action in parser._actions:
        choices = getattr(action, "choices", None)
        if choices and "build" in choices:
            return dict(choices)
    raise AssertionError("No argparse subcommands found")


def _long_options(parser: object) -> set[str]:
    return {
        option
        for action in parser._actions
        for option in action.option_strings
        if option.startswith("--") and option != "--help"
    }


def _is_external_or_generated_link(target: str) -> bool:
    return (
        target.startswith(("http://", "https://", "mailto:"))
        or target.startswith("#fn")
        or target.endswith((".png", ".jpg", ".jpeg", ".gif", ".svg"))
    )


def _anchors(text: str) -> set[str]:
    anchors: set[str] = set()
    for line in text.splitlines():
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if not match:
            continue
        heading = re.sub(r"`([^`]+)`", r"\1", match.group(2))
        heading = heading.lower()
        heading = re.sub(r"[^a-z0-9 -]", "", heading)
        heading = re.sub(r"\s+", "-", heading.strip())
        anchors.add(heading)
    return anchors

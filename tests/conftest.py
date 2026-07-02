from __future__ import annotations

from pathlib import Path

import pytest

from oddsgraph.build import build
from tests.synthetic import write_synthetic_input


@pytest.fixture(scope="session")
def synthetic_input(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("synthetic") / "synthetic.parquet"
    write_synthetic_input(path)
    return path


@pytest.fixture(scope="session")
def synthetic_output(tmp_path_factory: pytest.TempPathFactory, synthetic_input: Path) -> Path:
    out = tmp_path_factory.mktemp("synthetic_build") / "out"
    build(synthetic_input, out)
    return out

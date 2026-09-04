"""Factory manager tests, centred on the never-overwrite guarantee."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dashboard.factory.manager import (
    FactoryStatus,
    ensure_factory,
    factory_state,
    generate_demo_factory,
    load_factory,
    write_factory,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_FACTORY = PROJECT_ROOT / "simulation" / "config" / "factory.json"


class TestEnsureFactory:
    def test_generates_when_missing(self, tmp_path: Path):
        path = tmp_path / "nested" / "factory.json"
        state = ensure_factory(path, seed=5)
        assert state.status == FactoryStatus.VALID
        assert state.is_demo
        assert path.is_file()

    def test_loads_existing_without_rewriting(self, tmp_path: Path):
        path = tmp_path / "factory.json"
        ensure_factory(path, seed=5)
        original = path.read_bytes()

        state = ensure_factory(path, seed=999)

        assert path.read_bytes() == original, "existing factory.json must not be rewritten"
        assert state.status == FactoryStatus.VALID

    def test_does_not_generate_when_disallowed(self, tmp_path: Path):
        path = tmp_path / "factory.json"
        state = ensure_factory(path, allow_generate=False)
        assert state.status == FactoryStatus.MISSING
        assert not path.exists()

    def test_invalid_existing_file_is_reported_not_replaced(self, tmp_path: Path):
        path = tmp_path / "factory.json"
        path.write_text(json.dumps({"stations": []}), encoding="utf-8")
        before = path.read_bytes()

        state = ensure_factory(path)

        assert state.status == FactoryStatus.INVALID
        assert state.validation.errors
        assert path.read_bytes() == before

    def test_unparseable_existing_file_is_reported_not_replaced(self, tmp_path: Path):
        path = tmp_path / "factory.json"
        path.write_text("{oops", encoding="utf-8")
        state = ensure_factory(path)
        assert state.status == FactoryStatus.INVALID
        assert path.read_text(encoding="utf-8") == "{oops"

    def test_repository_factory_loads_as_valid(self):
        state = ensure_factory(REPO_FACTORY, allow_generate=False)
        assert state.status == FactoryStatus.VALID
        assert not state.is_demo
        assert state.station_count > 0


class TestOverwriteProtection:
    def test_generate_demo_refuses_existing_path(self, tmp_path: Path):
        path = tmp_path / "factory.json"
        path.write_text("{}", encoding="utf-8")
        with pytest.raises(FileExistsError):
            generate_demo_factory(path)
        assert path.read_text(encoding="utf-8") == "{}"

    def test_generate_demo_overwrites_only_when_asked(self, tmp_path: Path):
        path = tmp_path / "factory.json"
        path.write_text("{}", encoding="utf-8")
        state = generate_demo_factory(path, overwrite=True)
        assert state.status == FactoryStatus.VALID

    def test_write_factory_refuses_existing_path(self, tmp_path: Path):
        path = tmp_path / "factory.json"
        path.write_text("{}", encoding="utf-8")
        with pytest.raises(FileExistsError):
            write_factory(path, {"stations": []})

    def test_write_factory_refuses_invalid_payload(self, tmp_path: Path):
        with pytest.raises(ValueError):
            write_factory(tmp_path / "factory.json", {"stations": []})


class TestFactoryState:
    def test_missing_path(self, tmp_path: Path):
        state = factory_state(tmp_path / "absent.json")
        assert state.status == FactoryStatus.MISSING
        assert state.station_count == 0
        assert state.dark_zone_count == 0
        assert not state.exists

    def test_coverage_counts(self, tmp_path: Path):
        state = ensure_factory(tmp_path / "factory.json", seed=3)
        counts = state.sensor_coverage_counts()
        assert sum(counts.values()) == state.station_count


class TestLoadFactory:
    def test_raises_for_missing(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            load_factory(tmp_path / "absent.json")

    def test_raises_for_invalid(self, tmp_path: Path):
        path = tmp_path / "factory.json"
        path.write_text(json.dumps({"stations": []}), encoding="utf-8")
        with pytest.raises(ValueError):
            load_factory(path)

    def test_round_trips_generated_file(self, tmp_path: Path):
        path = tmp_path / "factory.json"
        generate_demo_factory(path, seed=11)
        assert load_factory(path)["_seed"] == 11

"""Streamlit shell smoke tests.

Runs the real ``dashboard/app.py`` headlessly through Streamlit's AppTest harness with
every prerequisite pointed at an empty temporary directory. This is the direct check
that the shell renders -- rather than raises -- when there is no factory.json, no
database, no completed runs, no prediction files and no running runtime.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("streamlit", reason="dashboard/requirements.txt not installed")

from streamlit.testing.v1 import AppTest  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP = PROJECT_ROOT / "dashboard" / "app.py"

#: Navigation order the dashboard must expose. Run Factory first (also the landing
#: page); Supervisor/Plant Manager/Leadership are peers, not nested behind one page.
EXPECTED_PAGES = [
    "Run Factory",
    "Supervisor",
    "Plant Manager",
    "Leadership",
    "Live Twin",
    "Bottlenecks",
    "Defects",
    "Sensor Coverage",
    "Run History",
]


def _launch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **env: str) -> AppTest:
    monkeypatch.setenv("DT_DASHBOARD_FACTORY", str(tmp_path / "config" / "factory.json"))
    monkeypatch.setenv("DT_DASHBOARD_DB", str(tmp_path / "db" / "dashboard.db"))
    monkeypatch.setenv("DT_DASHBOARD_RUNS", str(tmp_path / "runs"))
    monkeypatch.setenv("DT_DASHBOARD_GENERATED", str(tmp_path / "generated"))
    monkeypatch.setenv("DT_DASHBOARD_PREDICTIONS", str(tmp_path / "runtime_output"))
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    app = AppTest.from_file(str(APP), default_timeout=60)
    app.run()
    return app


def _text(app: AppTest) -> str:
    parts = []
    for collection in (app.markdown, app.caption, app.info, app.warning, app.error, app.title):
        parts.extend(element.value for element in collection)
    for element in app.sidebar.markdown:
        parts.append(element.value)
    return "\n".join(str(part) for part in parts)


class TestColdStart:
    def test_renders_with_nothing_in_place(self, tmp_path: Path, monkeypatch):
        app = _launch(tmp_path, monkeypatch)
        assert not app.exception, [str(e) for e in app.exception]

    def test_shows_the_product_name(self, tmp_path: Path, monkeypatch):
        app = _launch(tmp_path, monkeypatch)
        assert any("DIGITALTWIN.AI" in str(t.value) for t in app.title)

    def test_navigation_matches_the_required_page_set_and_order(self, tmp_path: Path, monkeypatch):
        """Run Factory, the three stakeholder views as peers, then the rest. No What-If."""
        app = _launch(tmp_path, monkeypatch)
        pages = list(app.sidebar.radio[0].options)
        assert pages == EXPECTED_PAGES

    def test_supervisor_plant_manager_leadership_are_directly_selectable(
        self, tmp_path: Path, monkeypatch
    ):
        """They must be peers in the main navigation, not nested behind one page."""
        app = _launch(tmp_path, monkeypatch)
        pages = list(app.sidebar.radio[0].options)
        for page in ("Supervisor", "Plant Manager", "Leadership"):
            assert page in pages
        # Only one navigation control exists now -- no separate "stakeholder mode".
        assert len(app.sidebar.radio) == 1

    def test_what_if_is_gone(self, tmp_path: Path, monkeypatch):
        app = _launch(tmp_path, monkeypatch)
        pages = list(app.sidebar.radio[0].options)
        assert "What-If" not in pages
        assert "What If" not in pages

    def test_reports_a_missing_factory_without_crashing(self, tmp_path: Path, monkeypatch):
        app = _launch(tmp_path, monkeypatch, DT_DASHBOARD_ALLOW_DEMO_FACTORY="false")
        assert not app.exception, [str(e) for e in app.exception]
        assert "MISSING" in _text(app)

    def test_reports_an_invalid_factory_without_crashing(self, tmp_path: Path, monkeypatch):
        factory = tmp_path / "config" / "factory.json"
        factory.parent.mkdir(parents=True)
        factory.write_text('{"stations": []}', encoding="utf-8")
        app = _launch(tmp_path, monkeypatch)
        assert not app.exception, [str(e) for e in app.exception]
        assert "INVALID" in _text(app)

    def test_generated_demo_factory_is_labelled(self, tmp_path: Path, monkeypatch):
        app = _launch(tmp_path, monkeypatch)
        assert not app.exception
        assert "illustrative" in _text(app).lower()


class TestNoExecutionOnLoad:
    def test_page_load_starts_no_run(self, tmp_path: Path, monkeypatch):
        app = _launch(tmp_path, monkeypatch)
        assert not app.exception
        assert not (tmp_path / "runs").exists()
        assert not (tmp_path / "generated").exists()
        assert not (tmp_path / "runtime_output").exists()

    def test_run_factory_button_is_present_but_idle(self, tmp_path: Path, monkeypatch):
        """Run Factory is the landing page (index 0), so the button needs no navigation."""
        app = _launch(tmp_path, monkeypatch)
        labels = [button.label for button in app.button]
        assert any("RUN FACTORY" in label for label in labels)
        assert not (tmp_path / "runs").exists()


class TestRunFactoryIsItsOwnPage:
    """The controls the task moved off every analysis page and onto one dedicated page."""

    def test_run_factory_controls_are_not_on_other_pages(self, tmp_path: Path, monkeypatch):
        app = _launch(tmp_path, monkeypatch)
        app.sidebar.radio[0].set_value("Bottlenecks").run()
        assert not app.exception, [str(e) for e in app.exception]
        labels = [button.label for button in app.button]
        assert not any("RUN FACTORY" in label for label in labels)

    @pytest.mark.parametrize(
        "page",
        ["Supervisor", "Plant Manager", "Leadership", "Live Twin", "Defects",
         "Sensor Coverage", "Run History"],
    )
    def test_no_page_besides_run_factory_shows_the_button(self, tmp_path: Path, monkeypatch, page: str):
        app = _launch(tmp_path, monkeypatch)
        app.sidebar.radio[0].set_value(page).run()
        assert not app.exception, [str(e) for e in app.exception]
        labels = [button.label for button in app.button]
        assert not any("RUN FACTORY" in label for label in labels)

    def test_playback_speed_control_lives_on_run_factory(self, tmp_path: Path, monkeypatch):
        app = _launch(tmp_path, monkeypatch)
        labels = [str(s.label) for s in app.sidebar.slider] + [str(s.label) for s in app.slider]
        assert any("Playback Speed" in label for label in labels)


class TestRunHistoryView:
    def test_empty_history_states_so_explicitly(self, tmp_path: Path, monkeypatch):
        app = _launch(tmp_path, monkeypatch)
        app.sidebar.radio[0].set_value("Run History").run()
        assert not app.exception, [str(e) for e in app.exception]
        assert "No completed production runs yet." in _text(app)

    def test_sensor_coverage_renders_from_the_factory(self, tmp_path: Path, monkeypatch):
        app = _launch(tmp_path, monkeypatch)
        app.sidebar.radio[0].set_value("Sensor Coverage").run()
        assert not app.exception, [str(e) for e in app.exception]

    @pytest.mark.parametrize(
        "page",
        ["Live Twin", "Bottlenecks", "Defects", "Supervisor", "Plant Manager", "Leadership"],
    )
    def test_pages_render(self, tmp_path: Path, monkeypatch, page: str):
        app = _launch(tmp_path, monkeypatch)
        app.sidebar.radio[0].set_value(page).run()
        assert not app.exception, [str(e) for e in app.exception]


class TestRunFactoryCommand:
    """The button must produce a command that is verified, not merely templated."""

    def _open_run_factory(self, tmp_path: Path, monkeypatch) -> AppTest:
        # Run Factory is the default landing page (index 0); still navigate explicitly
        # so this test does not depend on that default staying true.
        app = _launch(tmp_path, monkeypatch)
        return app.sidebar.radio[0].set_value("Run Factory").run()

    def _click_run_factory(self, app: AppTest) -> AppTest:
        for button in app.button:
            if "RUN FACTORY" in button.label:
                return button.click().run()
        raise AssertionError("RUN FACTORY button not found")

    def test_clicking_shows_a_command_or_a_blocker(self, tmp_path: Path, monkeypatch):
        app = self._click_run_factory(self._open_run_factory(tmp_path, monkeypatch))
        assert not app.exception, [str(e) for e in app.exception]
        shown = "\n".join(str(block.value) for block in app.code)
        errors = "\n".join(str(e.value) for e in app.error)
        assert ("cli.py" in shown) or errors, "neither a command nor a blocker was shown"

    def test_command_carries_the_utf8_environment(self, tmp_path: Path, monkeypatch):
        """Without PYTHONUTF8 the defect consumer dies on a cp1252 encode error."""
        app = self._click_run_factory(self._open_run_factory(tmp_path, monkeypatch))
        shown = "\n".join(str(block.value) for block in app.code)
        if "cli.py" in shown:
            assert "PYTHONUTF8" in shown

    def test_command_pins_a_verified_bottleneck_model(self, tmp_path: Path, monkeypatch):
        app = self._click_run_factory(self._open_run_factory(tmp_path, monkeypatch))
        shown = "\n".join(str(block.value) for block in app.code)
        if "system run random" in shown:
            assert "--bottleneck-model-id" in shown

    def test_clicking_starts_no_run(self, tmp_path: Path, monkeypatch):
        app = self._click_run_factory(self._open_run_factory(tmp_path, monkeypatch))
        assert not app.exception
        assert not (tmp_path / "runs").exists()
        assert not (tmp_path / "generated").exists()

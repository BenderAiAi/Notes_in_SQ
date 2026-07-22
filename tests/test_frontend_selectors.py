from pathlib import Path
import re


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _read(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def test_literal_javascript_selectors_exist_in_template() -> None:
    scripts = [
        _read("notes_app/static/app.js"),
        _read("notes_app/static/terminations.js"),
    ]
    template = (PROJECT_ROOT / "notes_app/templates/index.html").read_text(
        encoding="utf-8"
    )
    template_ids = set(re.findall(r'id="([^"]+)"', template))
    selector_ids = {
        selector
        for script in scripts
        for selector in re.findall(r'\$\$?\("#([A-Za-z0-9_-]+)', script)
    }

    assert selector_ids <= template_ids


def test_dynamic_type_metric_selectors_use_termination_prefix() -> None:
    script = _read("notes_app/static/terminations.js")

    assert '$(`#term-${kind}-total`)' in script
    assert '$(`#term-${kind}-split`)' in script


def test_termination_action_card_stays_in_its_grid_column() -> None:
    stylesheet = _read("notes_app/static/app.css")

    rule = re.search(
        r"#term-report-tab\s+\.action-card\s*\{([^}]*)\}", stylesheet
    )

    assert rule is not None
    assert "position: static" in rule.group(1)
    assert re.search(
        r"#term-report-tab\s+\.contracts-card\s*\{[^}]*min-width:\s*0",
        stylesheet,
    )


def test_template_ids_and_references_are_consistent() -> None:
    template = _read("notes_app/templates/index.html")
    ids = re.findall(r'id="([^"]+)"', template)
    id_set = set(ids)

    assert len(ids) == len(id_set), "В HTML есть повторяющиеся id"

    for attribute in ("aria-labelledby", "data-close-modal", "data-target"):
        references = re.findall(rf'{attribute}="([^"]+)"', template)
        assert set(references) <= id_set, f"Некорректные ссылки {attribute}"

    tab_targets = {
        f"{value}-tab" for value in re.findall(r'data-tab="([^"]+)"', template)
    }
    assert tab_targets <= id_set

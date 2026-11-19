"""Step 2 with many regions: the two display groups, the small preview and the detailed preview.

The files are synthetic and written into the test's temporary folder. Which group a region belongs
to is checked against what the builder planted (its sheet, header row and number of data rows).
"""

from __future__ import annotations

import json

import pytest
from openpyxl import Workbook

from tests.ui import test_ui_frontend as fe

page = fe.page  # the interface script running against the real local server
_run = fe._run
_click = fe._click


def _many_regions(path) -> None:
    """Four sheets: a 12-row table, a title, a note, a 4-row and a 5-row table, eight 2-row lists,
    a 40-column table, a headerless numeric table and a sheet of notes. Every value is invented."""
    wb = Workbook()
    a = wb.active
    assert a is not None
    a.title = "Summary"
    a.append(["Quarterly overview (invented figures)"])
    a.append([])
    a.append(["region_code", "units", "price", "opened", "status"])
    for i in range(12):
        a.append([f"R{i:03d}", i * 3 + 1, 2.5 + i, f"2024-01-{i + 1:02d}", "open" if i % 2 else "closed"])
    a.append([])
    a.append([])
    a.append(["All figures above are synthetic."])
    a.append([])
    a.append([])
    a.append(["code", "label", "rank"])  # row 21: four data rows
    for i in range(4):
        a.append([f"K{i}", f"lab{i}", i + 1])
    a.append([])
    a.append([])
    a.append(["batch", "weight", "grade"])  # row 28: five data rows
    for i in range(5):
        a.append([f"B{i}", 10 + i, "abc"[i % 3]])
    b = wb.create_sheet("Lists")
    r = 1
    for t in range(8):
        b.cell(r, 1, f"item_{t}")
        b.cell(r, 2, f"qty_{t}")
        b.cell(r + 1, 1, f"I{t}a")
        b.cell(r + 1, 2, t)
        b.cell(r + 2, 1, f"I{t}b")
        b.cell(r + 2, 2, t + 1)
        r += 5
    for j in range(40):  # row 41: a wide table
        b.cell(r, j + 1, f"wide_{j}")
    for k in range(8):
        for j in range(40):
            b.cell(r + 1 + k, j + 1, k * 100 + j)
    n = wb.create_sheet("Numbers")
    for k in range(6):
        n.append([(k + 1) * (j + 2) * 1.5 for j in range(4)])
    c = wb.create_sheet("Notes")
    c.append(["Read me first"])
    c.append([])
    c.append(["This workbook is synthetic."])
    c.append(["Nothing here is real."])
    wb.save(path)


def _small_only(path) -> None:
    path.write_text("Price list (invented)\n\nitem,price\nA,1\nB,2\nC,3\n\n\nzone,count,flag\nN,4,y\nS,5,n\nE,6,y\nW,7,n\n\n"
                    "End of list\n", encoding="utf-8")


def _open(ctx, path) -> None:
    ctx.eval(f"document.getElementById('path').value = {json.dumps(str(path))}")
    _click(ctx, "btn-open")
    assert ctx.eval("__text('msg')") == ""


def _js(ctx, expr):
    return json.loads(ctx.eval(f"JSON.stringify({expr})"))


def _group_names(ctx, group: int) -> list[str]:
    # group 0: "Detected tables"; group 1: "Small regions and notes"
    return _js(ctx, f"document.getElementById('region-cards').children[{group}].walk([])"
                    ".filter((n) => n.className === 'rname').map((n) => n.textContent)")


def _index(ctx, sheet: str, first_row: int) -> int:
    i = ctx.eval(f"state.inspect.recipe.tables.findIndex((t) => t.sheet === {json.dumps(sheet)} && t.first_row === {first_row})")
    assert i >= 0, (sheet, first_row)
    return i


def _name(ctx, i: int) -> str:
    return ctx.eval(f"state.inspect.recipe.tables[{i}].name")


def _toggle_open(ctx, node: str) -> None:
    ctx.eval(f"(() => {{ const n = {node}; n.open = true; (n.listeners.toggle || []).forEach((f) => f()); }})()")
    _run(ctx)


@pytest.fixture()
def many(tmp_path):
    path = tmp_path / "many_regions.xlsx"
    _many_regions(path)
    return path


def test_regions_are_grouped_by_data_rows_without_changing_the_recipe(page, many):
    ctx = page
    _open(ctx, many)
    regions = _js(ctx, "state.inspect.recipe.tables")
    assert len(regions) >= 15  # many regions over four sheets
    main, small = _group_names(ctx, 0), _group_names(ctx, 1)
    # Every region is listed exactly once, in source order within its group.
    assert sorted(main + small) == sorted(t["name"] for t in regions)
    order = [t["name"] for t in regions]
    assert main == [x for x in order if x in main] and small == [x for x in order if x in small]
    # Planted sizes decide the group: 12 and 5 data rows are tables; 4 and 2 data rows, the title and the notes are small.
    twelve, five, four = _index(ctx, "Summary", 3), _index(ctx, "Summary", 28), _index(ctx, "Summary", 21)
    wide, headerless = _index(ctx, "Lists", 41), _index(ctx, "Numbers", 1)
    for i in (twelve, five, wide, headerless):
        assert _name(ctx, i) in main
    for i in [four, _index(ctx, "Summary", 1), _index(ctx, "Notes", 1)] + [_index(ctx, "Lists", 1 + 5 * k) for k in range(8)]:
        assert _name(ctx, i) in small
    # Each group shows its count; the small group is collapsed and says that it may hold useful tables.
    cards = ctx.eval("__text('region-cards')")
    assert f"Detected tables  ({len(main)})" in cards and f"Small regions and notes  ({len(small)})" in cards
    assert "may still be useful tables" in cards
    assert ctx.eval("!!document.getElementById('region-cards').children[1].open") is False
    # A line names the sheet, the data rows (header excluded), the columns and the detection status.
    line = ctx.eval(f"state.cards[{twelve}].children[0].textContent")
    assert "Sheet Summary · 12 data rows · 5 columns" in line and "detected automatically" in line
    assert "Sheet Summary · 4 data rows · 3 columns" in ctx.eval(f"state.cards[{four}].children[0].textContent")
    assert "6 data rows · 4 columns · no header row" in ctx.eval(f"state.cards[{headerless}].children[0].textContent")
    # Grouping is display only: the recipe still holds every region, all in use, none confirmed.
    assert all(t["include"] for t in regions) and ctx.eval("__text('recipe-state')") == ""
    assert "You have not confirmed any region yet" in ctx.eval("__text('glance')")
    assert f"{len(main)} table(s) have 5 or more data rows" in ctx.eval("__text('glance')")
    # The form fields of every region are still there, in the cards and in the technical details.
    assert ctx.eval("__count('#region-cards [data-i]')") == 3 * len(regions)
    assert ctx.eval("__count('#regions [data-i]')") == 5 * len(regions)
    # The first large table is shown in the source viewer.
    assert ctx.eval("state.region") == twelve


def test_small_preview_detailed_preview_and_corrections(page, many):
    ctx = page
    _open(ctx, many)
    twelve, four = _index(ctx, "Summary", 3), _index(ctx, "Summary", 21)
    wide, headerless = _index(ctx, "Lists", 41), _index(ctx, "Numbers", 1)
    recipe_before = ctx.eval("JSON.stringify(state.inspect.recipe)")
    assert ctx.eval(f"state.minis[{twelve}].textContent") == ""  # nothing is loaded before the line is opened
    # Opening a line loads its header and first five data rows.
    _toggle_open(ctx, f"state.cards[{twelve}]")
    mini = ctx.eval(f"state.minis[{twelve}].textContent")
    assert "region_code" in mini and "R000" in mini and "R004" in mini and "R005" not in mini
    assert "Header in row 3" in mini and "First 5 rows of 12 data row(s)" in mini and "Open detailed preview" in mini
    assert "Quarterly overview" not in mini  # the title above the table is not part of the small preview
    # A wide table: thirty columns are shown in a scrolling box, and the page says which.
    _toggle_open(ctx, f"state.cards[{wide}]")
    mini = ctx.eval(f"state.minis[{wide}].textContent")
    assert "wide_0" in mini and "wide_29" in mini and "wide_30" not in mini and "Columns 1–30 of 1–40 are shown" in mini
    assert "scroll" in ctx.eval(f"state.minis[{wide}].children[0].className")
    # A headerless table is shown with column numbers.
    _toggle_open(ctx, f"state.cards[{headerless}]")
    mini = ctx.eval(f"state.minis[{headerless}].textContent")
    assert "No header row" in mini and "col 1" in mini and "3" in mini
    # A region of the collapsed group: its small preview, then the detailed preview in the source viewer.
    _toggle_open(ctx, "document.getElementById('region-cards').children[1]")
    _toggle_open(ctx, f"state.cards[{four}]")
    mini = ctx.eval(f"state.minis[{four}].textContent")
    assert "code" in mini and "K0" in mini and "K3" in mini and "First 4 rows of 4 data row(s)" in mini
    ctx.eval(f"openDetailed({four})")
    _run(ctx)
    assert ctx.eval("state.region") == four and "sel" in ctx.eval(f"state.cards[{four}].className")
    assert "sel" not in ctx.eval(f"state.cards[{twelve}].className")
    name = _name(ctx, four)
    assert f"Your file: {name} and what surrounds it" in ctx.eval("__text('source-title')")
    assert f"selected region {name}: rows 21–25, columns 1–3, header in row 21" in ctx.eval("__text('source-pos')")
    source = ctx.eval("__text('source')")
    assert "21 · header" in source and "22 · data" in source
    # Rows above the region are shown as context, so its upper boundary can be checked.
    assert "Sheet Summary · rows 18–" in ctx.eval("__text('source-pos')") and "All figures above are synthetic." in source
    # Looking at previews changed nothing: no confirmation, no edit, no step withdrawn.
    assert ctx.eval("JSON.stringify(state.inspect.recipe)") == recipe_before
    assert ctx.eval("__text('recipe-state')") == "" and "confirmed by you" not in ctx.eval("__text('region-cards')")
    assert ctx.eval("document.getElementById('s-policy').hidden") is False
    # The boundary and header numbers are one click away from the line.
    ctx.eval(f"openCorrections({four})")
    assert ctx.eval("document.getElementById('regions-tech').open") is True
    assert ctx.eval(f"state.techInputs[{four}].dataset.i") == str(four)
    assert ctx.eval(f"state.techInputs[{four}].dataset.k") == "header_row"


def test_corrections_move_a_region_between_groups_after_applying(page, many):
    ctx = page
    _open(ctx, many)
    four = _index(ctx, "Summary", 21)
    name = _name(ctx, four)
    assert name in _group_names(ctx, 1)
    _toggle_open(ctx, "document.getElementById('region-cards').children[1]")
    # Edit the last data row of the 4-row table in the technical details: nothing moves until it is applied.
    ctx.eval(f"document.querySelectorAll('#regions [data-i]').filter((n) => n.dataset.i === '{four}' && n.dataset.k === 'last_data_row')[0].value = '26'")
    ctx.eval("__fire('regions-tech', 'change')")
    assert "Unapplied changes" in ctx.eval("__text('recipe-state')") and name in _group_names(ctx, 1)
    _click(ctx, "btn-recipe")
    assert ctx.eval("__text('msg')") == ""
    # Applied: five data rows now, so it is listed with the tables; every region is confirmed by you.
    assert name in _group_names(ctx, 0) and name not in _group_names(ctx, 1)
    assert "Sheet Summary · 5 data rows · 3 columns" in ctx.eval(f"state.cards[{four}].children[0].textContent")
    assert "confirmed by you" in ctx.eval(f"state.cards[{four}].children[0].textContent")
    # The small group keeps the state the user left it in, and previews are loaded again for the new boundaries.
    assert ctx.eval("document.getElementById('region-cards').children[1].open") is True
    assert ctx.eval(f"state.minis[{four}].textContent") == ""
    _toggle_open(ctx, f"state.cards[{four}]")
    assert "First 5 rows of 5 data row(s)" in ctx.eval(f"state.minis[{four}].textContent")


def test_the_new_classes_have_style_rules():
    with open(fe.os.path.join(fe.STATIC, "app.css"), encoding="utf-8") as fh:
        css = fh.read()
    for cls in ("rgroup", "count", "meta", "mini", "mini-grid", "mini-table", "small-btn", "card-fields"):
        assert "." + cls in css, cls


def test_a_file_with_only_small_regions(page, tmp_path):
    ctx = page
    path = tmp_path / "small_only.csv"
    _small_only(path)
    _open(ctx, path)
    assert _group_names(ctx, 0) == []
    small = _group_names(ctx, 1)
    assert len(small) == len(_js(ctx, "state.inspect.recipe.tables")) == 4
    cards = ctx.eval("__text('region-cards')")
    assert "No table with 5 or more data rows was found" in cards and "Small regions and notes  (4)" in cards
    # Nothing would be visible otherwise, so the small group is opened, and the first table is in the viewer.
    assert ctx.eval("document.getElementById('region-cards').children[1].open") is True
    first_table = ctx.eval("state.inspect.recipe.tables.findIndex((t) => t.kind === 'table')")
    assert ctx.eval("state.region") == first_table
    assert "header in row 3" in ctx.eval("__text('source-pos')")
    # A single-sheet file does not repeat the sheet on every line.
    assert "Sheet" not in ctx.eval(f"state.cards[{first_table}].children[0].textContent")
    assert "3 data rows · 2 columns" in ctx.eval(f"state.cards[{first_table}].children[0].textContent")
    assert "0 table(s) have 5 or more data rows" in ctx.eval("__text('glance')")
    # The small tables can still be analysed: grouping does not leave anything out.
    ctx.eval("document.getElementById('policies').walk([]).filter((n) => n.name === 'policy')[0].checked = true")
    _click(ctx, "btn-profile")
    assert ctx.eval("__text('msg')") == ""
    assert ctx.eval("state.contract.tables.length") == 2

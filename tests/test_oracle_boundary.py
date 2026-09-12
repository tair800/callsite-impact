"""The oracle boundary, enforced by parsing rather than by trust.

The measurement here is only worth something if the thing being measured cannot see the
answer key. Two paths would break that, and both are checked here.

The first is a Python import: anything under ``src/callsite_impact/classify/`` reaching into
``callsite_impact.oracle`` or naming ``CompilerLabel``. The second is subtler and further away — the
TypeScript fact extractor in ``harness/scripts/extract-facts.mjs`` is supposed to build an AST and
walk it. The moment it calls ``createProgram``, ``getTypeChecker`` or ``getPreEmitDiagnostics`` it
is running a type checker, and the "parsed facts" the classifier consumes have quietly become
compiler output. Nothing about the Python side would look different; the number would just improve.

**Why this is parsed and not grepped.** A guard that fires on a docstring saying "must never import
the oracle" is a guard someone disables, and the next thing it fires on is real. So the Python half
walks the AST and only real ``Name`` and ``Attribute`` nodes and real import statements count, and
the JavaScript half strips comments before matching on word boundaries. String literals are
deliberately *not* stripped: ``ts["getTypeChecker"]()`` is exactly the evasion worth catching.

**A limitation, stated.** The JavaScript comment stripper tracks string and template literals but
does not model regular-expression literals, so a quote character inside a regex could desynchronise
it. The Python half catches ``importlib.import_module("callsite_impact.oracle")`` by inspecting the
literal argument, but a module name assembled at runtime from pieces would evade it. Neither hole is
closed; both are written down.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "src"
CLASSIFY_PACKAGE = SOURCE_ROOT / "callsite_impact" / "classify"
EXTRACT_FACTS = ROOT / "harness" / "scripts" / "extract-facts.mjs"

#: The classification package may import these first-party modules and nothing else.
#:
#: An allowlist, not a ban list, and the difference is the finding that produced it. The first
#: version of this guard banned ``callsite_impact.oracle`` -- a package that **did not exist**, so
#: it forbade nothing. A review proved it by planting ``import callsite_impact.pipeline`` plus a
#: read of ``work/<pair>/labels.json``, giving the classifier the compiler's raw diagnostics with
#: all sixteen tests green. A ban list only stops the routes somebody thought of.
#:
#: ``pipeline`` is the module that builds the answer key, and it is the one a shortcut reaches for.
#: It is absent from this list deliberately, not by oversight.
#:
#: The bare package name is deliberately absent too: ``callsite_impact`` here would make every
#: prefix match succeed and re-admit the whole repository.
ALLOWED_FIRST_PARTY_IMPORTS = frozenset(
    {
        "callsite_impact.domain",
        "callsite_impact.classify",
        "callsite_impact.specdiff",
    }
)

#: Filenames the oracle writes. A classifier that opens one is reading the answer key whatever it
#: imported to get there, so the guard looks for the strings as well as for the imports.
ORACLE_ARTEFACTS = ("labels.json", "admission.json")
GROUND_TRUTH_TYPE = "CompilerLabel"
DYNAMIC_IMPORT_CALLS = frozenset({"__import__", "import_module"})

TYPE_CHECKER_ENTRY_POINTS = ("createProgram", "getTypeChecker", "getPreEmitDiagnostics")


def _classify_modules() -> list[Path]:
    """Every Python module in the classification package. Fails loudly if the package is empty."""
    modules = sorted(CLASSIFY_PACKAGE.rglob("*.py"))
    assert modules, f"no modules found under {CLASSIFY_PACKAGE}; the guard would pass vacuously"
    return modules


def _package_of(module_path: Path) -> str:
    """The dotted package a module lives in, so relative imports can be resolved to absolute names.

    Args:
        module_path: Path to a ``.py`` file under ``src/``.

    Returns:
        The containing package, e.g. ``callsite_impact.classify``.
    """
    relative = module_path.relative_to(SOURCE_ROOT)
    return ".".join(relative.parts[:-1])


def _import_targets(tree: ast.AST, package: str) -> list[str]:
    """Every module name a source file imports, with relative imports resolved against ``package``.

    ``from . import oracle`` and ``from ..oracle import CompilerLabel`` name the same module as
    ``import callsite_impact.oracle``; a guard that only understood the absolute spelling would be
    trivially sidestepped.

    Args:
        tree: A parsed module.
        package: The dotted package the module lives in.

    Returns:
        Absolute dotted names, including the per-alias names of ``from X import Y`` forms, because
        ``Y`` may itself be the module.
    """
    targets: list[str] = []
    parts = package.split(".") if package else []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                base = node.module or ""
            else:
                kept = parts[: max(0, len(parts) - (node.level - 1))]
                base = ".".join(kept)
                if node.module:
                    base = f"{base}.{node.module}" if base else node.module
            if base:
                targets.append(base)
            targets.extend(f"{base}.{alias.name}" if base else alias.name for alias in node.names)
    return targets


def _dynamic_import_arguments(tree: ast.AST) -> list[str]:
    """Literal module names passed to ``__import__`` or ``importlib.import_module``.

    Only literal arguments to those two calls are inspected, so a docstring or an unrelated string
    constant cannot trigger the guard.
    """
    names: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        called = (
            function.id
            if isinstance(function, ast.Name)
            else function.attr
            if isinstance(function, ast.Attribute)
            else None
        )
        if called not in DYNAMIC_IMPORT_CALLS:
            continue
        names.extend(
            argument.value
            for argument in node.args
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str)
        )
    return names


def _names_ground_truth_type(tree: ast.AST) -> bool:
    """True when the source *refers* to ``CompilerLabel`` as code, not merely names it in prose."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == GROUND_TRUTH_TYPE:
            return True
        if isinstance(node, ast.Attribute) and node.attr == GROUND_TRUTH_TYPE:
            return True
    return False


def _forbidden_first_party(name: str) -> bool:
    """True for a first-party import the classification package is not allowed to make.

    Third-party and standard-library imports are none of this guard's business: only modules inside
    this repository can carry compiler output. Anything under ``callsite_impact`` that is not on the
    allowlist is a breach, so a **new** module is forbidden by default rather than permitted until
    somebody remembers to ban it.

    Prefix matching is what lets ``from callsite_impact.domain import SpecChange`` through: that
    form yields both the module and ``callsite_impact.domain.SpecChange``, and the second is a
    symbol whose module is allowed.
    """
    if not (name == "callsite_impact" or name.startswith("callsite_impact.")):
        return False
    return not any(
        name == allowed or name.startswith(f"{allowed}.") for allowed in ALLOWED_FIRST_PARTY_IMPORTS
    )


def _strip_js_comments(source: str) -> str:
    """Remove JavaScript comments while leaving string and template literals intact.

    Comments are removed because a note explaining that the extractor never calls ``getTypeChecker``
    is exactly the innocent case that trains people to ignore a guard. Strings are kept because
    ``ts["getTypeChecker"]()`` is a real call wearing a string's clothes.

    Args:
        source: The contents of a ``.mjs`` file.

    Returns:
        The same source with line and block comments blanked out.
    """
    out: list[str] = []
    index = 0
    length = len(source)
    quote: str | None = None
    while index < length:
        character = source[index]
        if quote is not None:
            out.append(character)
            if character == "\\" and index + 1 < length:
                out.append(source[index + 1])
                index += 2
                continue
            if character == quote:
                quote = None
            index += 1
            continue
        if character in "\"'`":
            quote = character
            out.append(character)
            index += 1
            continue
        if character == "/" and index + 1 < length and source[index + 1] == "/":
            while index < length and source[index] != "\n":
                index += 1
            continue
        if character == "/" and index + 1 < length and source[index + 1] == "*":
            index += 2
            while index + 1 < length and not (source[index] == "*" and source[index + 1] == "/"):
                index += 1
            index += 2
            continue
        out.append(character)
        index += 1
    return "".join(out)


def _type_checker_calls(source: str) -> list[str]:
    """Type-checker entry points named in code, on word boundaries so substrings do not fire."""
    code = _strip_js_comments(source)
    return [
        entry_point
        for entry_point in TYPE_CHECKER_ENTRY_POINTS
        if re.search(rf"\b{re.escape(entry_point)}\b", code)
    ]


# ------------------------------------------------------------------------------------- the guards


def test_classify_package_imports_only_what_it_is_allowed_to() -> None:
    """The system under test must not be able to reach the answer key it is graded against."""
    offenders: list[str] = []
    for module_path in _classify_modules():
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        package = _package_of(module_path)
        for name in _import_targets(tree, package) + _dynamic_import_arguments(tree):
            if _forbidden_first_party(name):
                offenders.append(f"{module_path.relative_to(ROOT)} imports {name}")
    assert not offenders, (
        "the classification package imported a first-party module outside its allowlist: "
        + "; ".join(offenders)
        + ". If the import is legitimate, add it to ALLOWED_FIRST_PARTY_IMPORTS and say why."
    )


def test_classify_package_never_opens_an_oracle_artefact() -> None:
    """Imports are not the only route to the answer key; the files it writes are banned by name.

    The breach a review planted imported nothing suspicious at module level -- it read
    ``work/<pair>/labels.json`` off disk. An import guard cannot see that.
    """
    offenders: list[str] = []
    for module_path in _classify_modules():
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                offenders.extend(
                    f"{module_path.relative_to(ROOT)} names {artefact!r}"
                    for artefact in ORACLE_ARTEFACTS
                    if artefact in node.value
                )
    assert not offenders, "the classification package referenced an oracle artefact: " + "; ".join(
        offenders
    )


def test_classify_package_never_names_the_compiler_label() -> None:
    """Reaching for the ground-truth type is the same breach as importing its package."""
    offenders = [
        str(module_path.relative_to(ROOT))
        for module_path in _classify_modules()
        if _names_ground_truth_type(ast.parse(module_path.read_text(encoding="utf-8")))
    ]
    assert not offenders, f"{GROUND_TRUTH_TYPE} is referenced as code in: " + "; ".join(offenders)


def test_fact_extractor_never_reaches_for_the_type_checker() -> None:
    """Parsed facts must stay parsed facts; a type checker in the extractor is compiler output."""
    if not EXTRACT_FACTS.exists():
        pytest.skip(
            f"{EXTRACT_FACTS.relative_to(ROOT)} does not exist yet, so there is nothing to guard. "
            "This skip must disappear the moment the extractor lands."
        )
    found = _type_checker_calls(EXTRACT_FACTS.read_text(encoding="utf-8"))
    assert not found, (
        f"{EXTRACT_FACTS.relative_to(ROOT)} calls {', '.join(found)}; the extractor may parse and "
        "walk an AST, never typecheck"
    )


# ------------------------------------ the guards, guarded: they must fire, and must not misfire


@pytest.mark.parametrize(
    "source",
    [
        "import callsite_impact.oracle",
        "from callsite_impact.oracle import labels",
        "from callsite_impact import oracle",
        "from ..oracle import labels",
        "from .. import oracle",
        "import importlib\nimportlib.import_module('callsite_impact.oracle')",
    ],
)
def test_python_guard_fires_on_a_planted_import(source: str) -> None:
    """Every spelling of the same breach, including the relative and dynamic ones."""
    tree = ast.parse(source)
    names = _import_targets(tree, "callsite_impact.classify") + _dynamic_import_arguments(tree)
    assert any(_forbidden_first_party(name) for name in names), source


@pytest.mark.parametrize(
    "source",
    [
        '"""This module must never import callsite_impact.pipeline."""',
        "from callsite_impact.domain import SpecChange",
        "import callsite_impact.specdiff.expressibility",
        "from callsite_impact.specdiff.expressibility import expressibility_of",
        "PIPELINE_NOTE = 'callsite_impact.pipeline is off limits'",
        "import re",
        "from collections.abc import Sequence",
        "import pydantic",
    ],
)
def test_python_guard_stays_quiet_on_an_innocent_mention(source: str) -> None:
    """Prose about the rule is not a breach of it, and a guard that says otherwise gets ignored."""
    tree = ast.parse(source)
    names = _import_targets(tree, "callsite_impact.classify") + _dynamic_import_arguments(tree)
    assert not any(_forbidden_first_party(name) for name in names), source


def test_compiler_label_guard_distinguishes_prose_from_code() -> None:
    """A docstring naming the type is fine; an annotation or attribute access is not."""
    assert not _names_ground_truth_type(ast.parse('"""Never read a CompilerLabel here."""'))
    assert _names_ground_truth_type(ast.parse("def f(x: CompilerLabel) -> None: ..."))
    assert _names_ground_truth_type(ast.parse("y = domain.CompilerLabel"))


def test_javascript_guard_ignores_comments_but_not_bracket_access() -> None:
    """The comment is the innocent case; the bracket access is the evasion."""
    assert _type_checker_calls("// we never call ts.createProgram here\nparse(source);\n") == []
    assert _type_checker_calls("/* getTypeChecker is forbidden */\nwalk(ast);\n") == []
    assert _type_checker_calls('const c = ts["getTypeChecker"]();') == ["getTypeChecker"]
    assert _type_checker_calls("const p = ts.createProgram(files, options);") == ["createProgram"]


def test_javascript_guard_does_not_fire_on_a_substring() -> None:
    """``createProgramme`` is a different word; word boundaries keep the guard honest."""
    assert _type_checker_calls("function createProgrammeNotes() {}") == []

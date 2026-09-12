"""Materialise the vendor corpus into `corpus/upstream/` and record exactly what was fetched.

Run as ``python -m callsite_impact.corpus.acquire``.

Every revision below is an explicit pin. Nothing is discovered at run time -- no "newest commit", no
"latest tag" -- because a rule evaluated at run time gives a different corpus next week and the
numbers this repository publishes would quietly stop matching the specs they were computed from. The
rules that *chose* the pins are recorded as comments; the pins themselves are constants.

**A pin was already caught lying.** Stripe tags `v2470` and `v2484` were the intended pair. They are
distinct tags three days apart, and `openapi/spec3.json` is byte-identical in both -- SHA-256
f0e0fc8f... on each -- because Stripe tags on SDK release, not on spec change. That pair produces
zero changes and therefore zero labels. The pinned Stripe revisions are the two most recent commits
that actually modified the file, and :func:`main` warns whenever a pair's two sides hash the same,
so the next such pin fails loudly instead of silently contributing nothing.

All three sources are MIT licensed, verified from the `LICENSE` file in each repository.
"""

from __future__ import annotations

import argparse
import itertools
import shutil
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Final

from callsite_impact.corpus.manifest import (
    CorpusManifest,
    index_specs,
    load_manifest,
    resolve_local_path,
    save_manifest,
    sha256_of,
)
from callsite_impact.domain import SpecPair, VendorSpec
from callsite_impact.specdiff.oasdiff import oasdiff_version

__all__ = ["main"]

LICENCE: Final = "MIT"
UPSTREAM_DIR: Final = "corpus/upstream"
MANIFEST_PATH: Final = "corpus/manifest.json"
_HTTP_TIMEOUT_S: Final = 600
_GIT_TIMEOUT_S: Final = 1800


# ------------------------------------------------------------------------------------------- pins


@dataclass(frozen=True, slots=True)
class _GitPin:
    """A file at a pinned commit of a cloned repository."""

    vendor: str
    service: str
    revision: str
    revision_date: str
    repo: str
    commit: str
    path_in_repo: str


@dataclass(frozen=True, slots=True)
class _HttpPin:
    """A file fetched directly by URL, for repositories too large to clone."""

    vendor: str
    service: str
    revision: str
    revision_date: str
    url: str


_Pin = _GitPin | _HttpPin


def _short(revision: str) -> str:
    """Shorten a commit SHA for filenames and pair ids; version suffixes pass through untouched."""
    return revision[:12] if len(revision) == 40 else revision


REPOS: Final[dict[str, str]] = {
    "adyen": "https://github.com/Adyen/adyen-openapi",
    "xero": "https://github.com/XeroAPI/Xero-OpenAPI",
    "twilio": "https://github.com/twilio/twilio-oai",
}


# Adyen ships each API version as its own file on one branch, so the revision identity is the
# vendor's version suffix and the commit only fixes which bytes that suffix had. This commit is the
# most recent one touching all six Checkout files as of pinning.
_ADYEN_COMMIT: Final = "f0d0bd47b721d1b4e2c86e8b3aad706ecb88423a"
_ADYEN_COMMIT_DATE: Final = "2026-08-04T10:21:09+02:00"
_ADYEN_VERSIONS: Final = ("v67", "v68", "v69", "v70", "v71", "v72")

# Four Adyen services rather than one. Checkout alone would have made the corpus a statement about
# a single API's release habits: its six adjacent versions are mostly additive, and two of the five
# pairs break nothing at all. Adding services that version independently is the cheapest way to make
# the vendor's contribution a range instead of an anecdote -- and it is what surfaced
# BalancePlatform v1 -> v2, by a distance the largest single source of breakage in the corpus.
_ADYEN_SERVICES: Final = (
    ("checkout", "CheckoutService", _ADYEN_VERSIONS),
    ("balance-platform", "BalancePlatformService", ("v1", "v2")),
    ("account", "AccountService", ("v5", "v6")),
    ("bin-lookup", "BinLookupService", ("v52", "v53", "v54")),
)


def _adyen(service: str, file_stem: str, version: str) -> _GitPin:
    return _GitPin(
        vendor="adyen",
        service=service,
        revision=version,
        revision_date=_ADYEN_COMMIT_DATE,
        repo="adyen",
        commit=_ADYEN_COMMIT,
        path_in_repo=f"json/{file_stem}-{version}.json",
    )


# Xero keeps one file per API and rewrites it in place, so a revision here is a commit. The "before"
# side is the third-oldest commit touching each file -- old enough that six years of drift separate
# the two sides, late enough to skip the initial import commits, which are not valid specs on their
# own. The "after" side is one commit that touched all three files.
_XERO_AFTER: Final = "448060d7829cae23166a2e443be48c2f2422280f"
_XERO_AFTER_DATE: Final = "2026-09-03T22:30:59Z"


def _xero(service: str, filename: str, commit: str, date: str) -> _GitPin:
    return _GitPin(
        vendor="xero",
        service=service,
        revision=commit,
        revision_date=date,
        repo="xero",
        commit=commit,
        path_in_repo=filename,
    )


# Deliberately excluded, each verified by running the differ over the same third-oldest/newest pair:
#   xero_accounting.yaml -- oasdiff exits 104: "duplicate endpoint (GET /Contacts/{ContactNumber})".
#   xero-finance.yaml    -- oasdiff exits 102: YAML unmarshal failure at line 564 of the old spec.
#   xero-projects.yaml   -- oasdiff exits 102: bad data in "#/components/schemas/ChargeType"
#                           (expecting ref to parameter object).
# These are defects in the published specs, not in the differ. A spec the differ cannot read yields
# no changes and so no labels, and including it would only inflate the corpus count.
_XERO_SPECS: Final = (
    (
        "bankfeeds",
        "xero_bankfeeds.yaml",
        "33d2244c8f368889758fa758d26a04aeb6c55b68",
        "2020-09-25T13:19:01-07:00",
    ),
    (
        "payroll-au",
        "xero-payroll-au.yaml",
        "54d7cdb60c32e39df438babc570e79993d4518cc",
        "2020-09-24T13:30:57-07:00",
    ),
    (
        "files",
        "xero_files.yaml",
        "eca25676d52969bf6833eed83f5fe95d3ce47c53",
        "2020-09-24T13:27:40-07:00",
    ),
)


# ---------------------------------------------------------------------------------------- Stripe
#
# **Stripe was acquired, measured, and then removed from the corpus. It is recorded here rather than
# deleted, because "we tried four vendors and kept three" is a fact about the corpus.**
#
# The reason is reproducibility, not results. `oasdiff` does not finish on the pair below: the two
# revisions are ~8 MB each with a very large `anyOf` graph, and the differ was still running after
# **35 minutes of CPU** with no output, against seconds for every other pair in the corpus. A pair
# that cannot be re-diffed is a pair no reader can check and CI cannot re-measure, and the
# measurement being re-runnable on every push is the thing that keeps the published numbers honest.
#
# Removing it cannot flatter the kill criterion, and that is worth being explicit about: a separate
# probe over an even wider Stripe pair (tags v2380 -> v2484, 8,922 differ-reported breaking changes)
# admitted 434 call sites and produced **zero** compiler-verified breakages. Stripe contributed
# nothing to the 60-breakage threshold in either direction. That probe is not part of the measured
# result and is not counted anywhere; it is named here so the decision can be checked rather than
# taken on trust.
#
# stripe/openapi is also ~1 GB of history for one 8 MB file, so it was fetched by URL, never cloned.
_STRIPE_BEFORE: Final = ("af5309cae53e5f666f9686dfed306d6d3b5fdc67", "2026-07-29T18:38:34Z")
_STRIPE_AFTER: Final = ("30d3391cc09a0f67ad29bee002f570811b19e1da", "2026-08-26T17:57:44Z")


# Twilio publishes one file per product and rewrites each in place, so a revision is a commit. The
# "before" side is the repository's initial public import, which is a valid specification in its own
# right; the "after" side is the newest commit touching that file. The gap is roughly six years,
# which is why this vendor contributes the `response-property-became-nullable` class almost alone.
_TWILIO_BEFORE: Final = ("111a7cb947056d26ec77fed5f9365007de2a0ced", "2020-12-08T22:01:44Z")
_TWILIO_SPECS: Final = (
    (
        "flex",
        "twilio_flex_v1.json",
        "591755b562834daae097da2371e821f349c5f489",
        "2026-08-11T16:43:54+05:30",
    ),
    (
        "messaging",
        "twilio_messaging_v1.json",
        "5aa7f31977ce5812f7b7bc1f46a38555ebaa2888",
        "2026-09-09T16:12:33+05:30",
    ),
    (
        "verify",
        "twilio_verify_v2.json",
        "5aa7f31977ce5812f7b7bc1f46a38555ebaa2888",
        "2026-09-09T16:12:33+05:30",
    ),
    (
        "taskrouter",
        "twilio_taskrouter_v1.json",
        "55a17be6f0f130e5d529f92c0bf774254bb0f1d1",
        "2026-02-05T12:23:31Z",
    ),
    (
        "conversations",
        "twilio_conversations_v1.json",
        "591755b562834daae097da2371e821f349c5f489",
        "2026-08-11T16:43:54+05:30",
    ),
    (
        "events",
        "twilio_events_v1.json",
        "591755b562834daae097da2371e821f349c5f489",
        "2026-08-11T16:43:54+05:30",
    ),
)


def _twilio(service: str, filename: str, commit: str, date: str) -> _GitPin:
    return _GitPin(
        vendor="twilio",
        service=service,
        revision=commit,
        revision_date=date,
        repo="twilio",
        commit=commit,
        path_in_repo=f"spec/json/{filename}",
    )


def _stripe(commit: str, date: str) -> _HttpPin:
    return _HttpPin(
        vendor="stripe",
        service="core",
        revision=commit,
        revision_date=date,
        url=f"https://raw.githubusercontent.com/stripe/openapi/{commit}/openapi/spec3.json",
    )


def _build_pairs() -> tuple[tuple[str, _Pin, _Pin], ...]:
    """The pinned corpus as ``(pair_id, before, after)`` triples.

    Built by a function rather than written out as one literal because the Adyen side is five
    adjacent pairs over a sequence, and spelling those out invites a transcription error in exactly
    the data that is supposed to be trustworthy.
    """
    pairs: list[tuple[str, _Pin, _Pin]] = []

    for service, stem, versions in _ADYEN_SERVICES:
        for before_v, after_v in itertools.pairwise(versions):
            pairs.append(
                (
                    f"adyen-{service}-{before_v}-to-{after_v}",
                    _adyen(service, stem, before_v),
                    _adyen(service, stem, after_v),
                )
            )

    for service, filename, commit, date in _TWILIO_SPECS:
        before = _twilio(service, filename, *_TWILIO_BEFORE)
        after = _twilio(service, filename, commit, date)
        pairs.append(
            (
                f"twilio-{service}-{_short(_TWILIO_BEFORE[0])}-to-{_short(commit)}",
                before,
                after,
            )
        )

    for service, filename, commit, date in _XERO_SPECS:
        before = _xero(service, filename, commit, date)
        after = _xero(service, filename, _XERO_AFTER, _XERO_AFTER_DATE)
        pairs.append(
            (
                f"xero-{service}-{_short(commit)}-to-{_short(_XERO_AFTER)}",
                before,
                after,
            )
        )

    # Stripe is deliberately NOT in the corpus. See _STRIPE_* above for the whole reason.
    return tuple(pairs)


PAIRS: Final = _build_pairs()


# ------------------------------------------------------------------------------------ local paths


def repo_root() -> Path:
    """The repository root, inferred from this file's location.

    Returns:
        `.../callsite-impact`, four levels up from `src/callsite_impact/corpus/acquire.py`. The CLI
        exposes `--root` so an install that breaks this assumption is not stuck with it.
    """
    return Path(__file__).resolve().parents[3]


def _source_name(pin: _Pin) -> str:
    """The upstream file name, which is where the extension comes from."""
    return pin.path_in_repo if isinstance(pin, _GitPin) else pin.url


def _local_path(pin: _Pin) -> str:
    """Repo-root-relative POSIX path for a pin, so the manifest survives moving between machines."""
    suffix = PurePosixPath(_source_name(pin)).suffix or ".json"
    return f"{UPSTREAM_DIR}/specs/{pin.vendor}/{pin.service}-{_short(pin.revision)}{suffix}"


def _source_url(pin: _Pin) -> str:
    """A URL a reader can open to see this exact revision."""
    if isinstance(pin, _HttpPin):
        return pin.url
    return f"{REPOS[pin.repo]}/blob/{pin.commit}/{pin.path_in_repo}"


# --------------------------------------------------------------------------------- materialising


def _git(args: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=_GIT_TIMEOUT_S,
        check=False,
    )


def _ensure_checkout(root: Path, repo_key: str) -> Path:
    """Clone a source repository if it is not already on disk.

    Cloned with `--filter=blob:none`: the full commit graph is needed to reach a 2020 commit, but
    the file blobs for six years of unrelated history are not, and they are fetched on demand when
    `git show` asks for one.

    Args:
        root: Repository root.
        repo_key: Key into :data:`REPOS`.

    Returns:
        Path to the checkout.

    Raises:
        RuntimeError: If the clone fails, carrying git's stderr.
    """
    checkout = root / UPSTREAM_DIR / "checkouts" / repo_key
    if (checkout / ".git").is_dir():
        return checkout

    checkout.parent.mkdir(parents=True, exist_ok=True)
    print(f"  cloning {REPOS[repo_key]} -> {checkout.relative_to(root).as_posix()}")
    result = _git(["clone", "--filter=blob:none", REPOS[repo_key], str(checkout)])
    if result.returncode != 0:
        raise RuntimeError(f"git clone of {REPOS[repo_key]} failed: {result.stderr.strip()}")
    return checkout


def _ensure_commit(checkout: Path, commit: str) -> None:
    """Make sure a pinned commit is present, fetching it if an existing checkout predates it."""
    if _git(["cat-file", "-e", f"{commit}^{{commit}}"], cwd=checkout).returncode == 0:
        return
    fetched = _git(["fetch", "--filter=blob:none", "origin", commit], cwd=checkout)
    if fetched.returncode != 0:
        fetched = _git(["fetch", "origin"], cwd=checkout)
    if _git(["cat-file", "-e", f"{commit}^{{commit}}"], cwd=checkout).returncode != 0:
        raise RuntimeError(
            f"commit {commit} is not reachable in {checkout}: {fetched.stderr.strip()}"
        )


def _finalise(temporary: Path, destination: Path) -> None:
    """Move a fully written temporary file into place.

    Written to a sibling temporary first so that an interrupted fetch cannot leave a truncated spec
    that the next run would hash, find plausible, and accept as cached.
    """
    temporary.replace(destination)


def _materialise_git(pin: _GitPin, destination: Path, checkout: Path) -> None:
    """Extract a pinned file out of a checkout with `git show`, bytes unmodified."""
    _ensure_commit(checkout, pin.commit)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    with temporary.open("wb") as handle:
        result = subprocess.run(
            ["git", "show", f"{pin.commit}:{pin.path_in_repo}"],
            cwd=checkout,
            stdout=handle,
            stderr=subprocess.PIPE,
            timeout=_GIT_TIMEOUT_S,
            check=False,
        )
    if result.returncode != 0:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(
            f"git show {pin.commit}:{pin.path_in_repo} failed: "
            f"{result.stderr.decode('utf-8', 'replace').strip()}"
        )
    _finalise(temporary, destination)


def _materialise_http(pin: _HttpPin, destination: Path) -> None:
    """Download a pinned file. Only the constant https URLs in this module are ever fetched."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    try:
        with (
            urllib.request.urlopen(pin.url, timeout=_HTTP_TIMEOUT_S) as response,
            temporary.open("wb") as handle,
        ):
            shutil.copyfileobj(response, handle)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    _finalise(temporary, destination)


# ------------------------------------------------------------------------------------ the command


@dataclass(frozen=True, slots=True)
class _Acquired:
    """One materialised revision plus how it got there, for the summary table."""

    spec: VendorSpec
    cached: bool


def _acquire(
    pin: _Pin,
    root: Path,
    known: dict[tuple[str, str, str], VendorSpec],
    *,
    force: bool,
) -> _Acquired:
    """Materialise one revision, skipping the fetch when the bytes on disk are already right.

    Args:
        pin: The pinned revision.
        root: Repository root.
        known: Specs from the previous manifest, indexed by identity.
        force: Refetch even when the hash matches.

    Returns:
        The recorded spec and whether the fetch was skipped.
    """
    relative = _local_path(pin)
    destination = root / PurePosixPath(relative)
    identity = (pin.vendor, pin.service, pin.revision)
    previous = known.get(identity)

    if (
        not force
        and previous is not None
        and destination.is_file()
        and sha256_of(destination) == previous.sha256
    ):
        return _Acquired(spec=previous, cached=True)

    if isinstance(pin, _GitPin):
        _materialise_git(pin, destination, _ensure_checkout(root, pin.repo))
    else:
        _materialise_http(pin, destination)

    spec = VendorSpec(
        vendor=pin.vendor,
        service=pin.service,
        revision=pin.revision,
        revision_date=pin.revision_date,
        source_url=_source_url(pin),
        licence=LICENCE,
        sha256=sha256_of(destination),
        local_path=relative,
    )
    return _Acquired(spec=spec, cached=False)


def _print_summary(root: Path, manifest: CorpusManifest, cached: set[str]) -> int:
    """Print one row per pair and return the number of pairs whose two sides are identical.

    A pair whose sides hash the same is reported loudly rather than passed over. It costs nothing to
    diff and contributes nothing to the corpus, and the only reason anyone would ship one is that
    they assumed two revision identifiers implied two different documents. That assumption has
    already been wrong once here.
    """
    header = f"{'pair':<44} {'before':>10} {'after':>10}  {'MB':>6}  state"
    print(f"\n{header}\n{'-' * len(header)}")

    degenerate = 0
    for pair in manifest.pairs:
        size_mb = sum(
            resolve_local_path(root, spec).stat().st_size for spec in (pair.before, pair.after)
        ) / (1024 * 1024)
        state = (
            "cached" if pair.before.sha256 in cached and pair.after.sha256 in cached else "fetched"
        )
        print(
            f"{pair.pair_id:<44} {_short(pair.before.revision):>10} "
            f"{_short(pair.after.revision):>10}  {size_mb:6.1f}  {state}"
        )
        if pair.before.sha256 == pair.after.sha256:
            degenerate += 1
            print(f"{'':<44} !! both sides are byte-identical; this pair can produce no changes")

    print(
        f"\n{len(manifest.pairs)} pairs, {len(manifest.vendors)} vendors "
        f"({', '.join(manifest.vendors)}), differ: {manifest.oasdiff_version}"
    )
    return degenerate


def main(argv: list[str] | None = None) -> int:
    """Acquire the corpus and write `corpus/manifest.json`.

    Args:
        argv: Command-line arguments, for testing. Defaults to `sys.argv[1:]`.

    Returns:
        Process exit code. Non-zero if any pinned pair turned out to be degenerate, because a corpus
        that silently contains a no-op pair produces a smaller label count than its pair count
        suggests.
    """
    parser = argparse.ArgumentParser(
        prog="python -m callsite_impact.corpus.acquire",
        description="Materialise the pinned vendor spec corpus and record its provenance.",
    )
    parser.add_argument("--root", type=Path, default=repo_root(), help="repository root")
    parser.add_argument(
        "--generated-at",
        default=None,
        help="ISO-8601 timestamp to stamp the manifest with; defaults to now, in UTC",
    )
    parser.add_argument(
        "--force", action="store_true", help="refetch every spec even if its hash already matches"
    )
    args = parser.parse_args(argv)

    root: Path = args.root.resolve()
    generated_at: str = args.generated_at or datetime.now(UTC).isoformat(timespec="seconds")
    manifest_path = root / PurePosixPath(MANIFEST_PATH)

    known: dict[tuple[str, str, str], VendorSpec] = {}
    if manifest_path.is_file() and not args.force:
        known = index_specs(load_manifest(manifest_path))

    differ = oasdiff_version()

    acquired: dict[tuple[str, str, str], _Acquired] = {}
    pairs: list[SpecPair] = []
    for pair_id, before_pin, after_pin in PAIRS:
        print(f"{pair_id}")
        sides: list[VendorSpec] = []
        for pin in (before_pin, after_pin):
            identity = (pin.vendor, pin.service, pin.revision)
            if identity not in acquired:
                acquired[identity] = _acquire(pin, root, known, force=args.force)
            sides.append(acquired[identity].spec)
        pairs.append(
            SpecPair(
                pair_id=pair_id,
                vendor=before_pin.vendor,
                service=before_pin.service,
                before=sides[0],
                after=sides[1],
            )
        )

    manifest = CorpusManifest(generated_at=generated_at, oasdiff_version=differ, pairs=tuple(pairs))
    save_manifest(manifest, manifest_path)
    print(f"\nwrote {manifest_path.relative_to(root).as_posix()}")

    cached = {item.spec.sha256 for item in acquired.values() if item.cached}
    degenerate = _print_summary(root, manifest, cached)
    return 1 if degenerate else 0


if __name__ == "__main__":
    sys.exit(main())

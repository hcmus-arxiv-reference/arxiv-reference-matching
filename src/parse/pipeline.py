"""Pipeline tích hợp M2 (docs/m2-cong-viec.md mục 4.4):
Ghép các gói [A] Source -> [B, B'] Structure & BibSource -> [C] Leaves -> [D] BibTeX -> [E] Export,
hỗ trợ checkpoint/resume theo SHA-256 đầu vào và phiên bản các module, ghi log Version (C4),
lưu thứ tự anh em (C3), xuất 3 bảng Parquet và tổng hợp số liệu báo cáo.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import time
from typing import Any, Callable, Mapping, Sequence

from src.common.corpus import FileCorpus, file_digest, verified_source
from src.common.json_io import write_json
from src.common.metrics import dir_size_mb, peak_rss_mb
from src.common.schema import publication_key, require_id
from src.parse._fallback import (
    FALLBACK_BIBTEX_VERSION,
    FALLBACK_LEAVES_VERSION,
    FALLBACK_NORMALIZE_VERSION,
    fallback_build_leaves,
    fallback_merge_bibtex,
    fallback_normalize,
)
from src.parse.export import (
    EXPORT_VERSION,
    ExportResult,
    VersionInput,
    export_publication,
    merge_export_tables,
    validate_E,
    write_export_tables,
)
from src.parse.source import ASSEMBLER_VERSION, SourceBundle, assemble_source
from src.parse.structure import STRUCTURE_VERSION, build_structure
from src.parse.types import (
    TYPES_VERSION,
    BibResult,
    BibSource,
    LeafTree,
    StructureTree,
    validate_A,
    validate_B,
    validate_B_prime,
    validate_C,
    validate_D,
)

PIPELINE_VERSION = "2"


def _resolve_stage_functions(
    *,
    allow_fallback: bool = False,
    assemble_fn: Callable[[Path], SourceBundle] | None = None,
    structure_fn: Callable[..., tuple[StructureTree, BibSource]] | None = None,
    leaves_fn: Callable[[StructureTree], LeafTree] | None = None,
    bibtex_fn: Callable[[str, list[BibSource]], BibResult] | None = None,
    normalize_fn: Callable[[str, str], str] | None = None,
) -> tuple[
    Callable[[Path], SourceBundle],
    Callable[..., tuple[StructureTree, BibSource]],
    Callable[[StructureTree], LeafTree],
    Callable[[str, list[BibSource]], BibResult],
    Callable[[str, str], str],
    list[str],
]:
    """Nạp các hàm thực thi cho từng bước M2; chỉ dùng fallback tạm khi `allow_fallback=True`."""
    assembler = assemble_fn or assemble_source
    structure = structure_fn or build_structure
    active_fallbacks: list[str] = []
    missing_modules: list[str] = []

    leaves = leaves_fn
    if leaves is None:
        try:
            from src.parse.leaves import build_leaves as leaves  # type: ignore[import-not-found]
        except ImportError:
            if allow_fallback:
                leaves = fallback_build_leaves
                active_fallbacks.append("leaves")
            else:
                missing_modules.append("src.parse.leaves")

    bibtex = bibtex_fn
    if bibtex is None:
        try:
            from src.parse.bibtex import merge_bibtex as bibtex  # type: ignore[import-not-found]
        except ImportError:
            if allow_fallback:
                bibtex = fallback_merge_bibtex
                active_fallbacks.append("bibtex")
            else:
                missing_modules.append("src.parse.bibtex")

    normalizer = normalize_fn
    if normalizer is None:
        try:
            from src.parse.normalize import normalize as normalizer  # type: ignore[import-not-found]
        except ImportError:
            if allow_fallback:
                normalizer = fallback_normalize
                active_fallbacks.append("normalize")
            else:
                missing_modules.append("src.parse.normalize")

    if missing_modules:
        joined = ", ".join(missing_modules)
        raise ImportError(
            f"Thiếu gói thật trên nhánh hiện tại: {joined}. "
            "Cần merge các PR còn lại vào `main`, hoặc bật cờ `allow_fallback=True` "
            "(`--allow-fallback` ở CLI) nếu muốn chạy thử bằng bản thay thế tạm."
        )

    assert leaves is not None and bibtex is not None and normalizer is not None
    return assembler, structure, leaves, bibtex, normalizer, sorted(active_fallbacks)


def get_module_versions(*, allow_fallback: bool = False) -> dict[str, str]:
    """Lấy phiên bản của mọi module trong pipeline để ghi nhận vào checkpoint done.json."""
    versions = {
        "assembler": str(ASSEMBLER_VERSION),
        "structure": str(STRUCTURE_VERSION),
        "leaves": FALLBACK_LEAVES_VERSION if allow_fallback else "missing",
        "normalize": FALLBACK_NORMALIZE_VERSION if allow_fallback else "missing",
        "bibtex": FALLBACK_BIBTEX_VERSION if allow_fallback else "missing",
        "types": str(TYPES_VERSION),
        "export": str(EXPORT_VERSION),
        "pipeline": str(PIPELINE_VERSION),
    }
    try:
        from src.parse.leaves import LEAVES_VERSION  # type: ignore[import-not-found]

        versions["leaves"] = str(LEAVES_VERSION)
    except ImportError:
        pass
    try:
        from src.parse.normalize import NORMALIZE_VERSION  # type: ignore[import-not-found]

        versions["normalize"] = str(NORMALIZE_VERSION)
    except ImportError:
        pass
    try:
        from src.parse.bibtex import BIBTEX_VERSION  # type: ignore[import-not-found]

        versions["bibtex"] = str(BIBTEX_VERSION)
    except ImportError:
        pass
    return versions


def compute_publication_input_sha256(corpus: FileCorpus, arxiv_id: str, total_versions: int) -> str:
    """Băm tất định metadata.json và source.json của mọi Version thuộc Publication."""
    meta_path = corpus.metadata_path(arxiv_id)
    meta_hash = file_digest(meta_path) if meta_path.exists() else "missing"
    ver_hashes: list[str] = []
    for ver in range(1, total_versions + 1):
        vdir = corpus.version_path(arxiv_id, ver)
        receipt = vdir / "source.json"
        if receipt.exists():
            ver_hashes.append(f"v{ver}:{file_digest(receipt)}")
        else:
            ver_hashes.append(f"v{ver}:missing")
    payload = json.dumps(
        {"arxiv_id": arxiv_id, "metadata": meta_hash, "versions": ver_hashes},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _save_publication_checkpoint(
    parse_dir: Path,
    result: ExportResult,
    input_sha256: str,
    module_versions: Mapping[str, str],
) -> None:
    """Lưu order.json (C3), export.json (cache trung gian) và done.json (checkpoint)."""
    key = publication_key(result.arxiv_id)
    pub_dir = parse_dir / key
    pub_dir.mkdir(parents=True, exist_ok=True)
    write_json(pub_dir / "order.json", result.order)
    write_json(
        pub_dir / "export.json",
        {
            "arxiv_id": result.arxiv_id,
            "elements": result.elements,
            "hierarchy": result.hierarchy,
            "bibtex": result.bibtex,
            "version_logs": result.version_logs,
            "stats": result.stats,
            "root_by_version": {str(k): v for k, v in result.root_by_version.items()},
        },
    )
    write_json(
        pub_dir / "done.json",
        {
            "format": 1,
            "arxiv_id": result.arxiv_id,
            "input_sha256": input_sha256,
            "module_versions": dict(module_versions),
        },
    )


def _load_publication_checkpoint(
    parse_dir: Path,
    arxiv_id: str,
    input_sha256: str,
    module_versions: Mapping[str, str],
    expected_versions: int,
) -> ExportResult | None:
    """Đọc lại kết quả đã lưu nếu done.json khớp input_sha256 và module_versions."""
    key = publication_key(arxiv_id)
    pub_dir = parse_dir / key
    done_path = pub_dir / "done.json"
    export_path = pub_dir / "export.json"
    order_path = pub_dir / "order.json"
    if not (done_path.is_file() and export_path.is_file() and order_path.is_file()):
        return None
    try:
        done = json.loads(done_path.read_text(encoding="utf-8"))
        if (
            done.get("format") != 1
            or done.get("arxiv_id") != arxiv_id
            or done.get("input_sha256") != input_sha256
            or done.get("module_versions") != dict(module_versions)
        ):
            return None
        cached = json.loads(export_path.read_text(encoding="utf-8"))
        order = json.loads(order_path.read_text(encoding="utf-8"))
        result = ExportResult(
            arxiv_id=cached["arxiv_id"],
            elements=cached["elements"],
            hierarchy=cached["hierarchy"],
            bibtex=cached["bibtex"],
            version_logs=cached["version_logs"],
            order=order,
            stats=cached["stats"],
            root_by_version={
                int(k): v for k, v in cached.get("root_by_version", {}).items()
            },
        )
        validate_E(result, expected_versions=expected_versions, raise_on_error=True)
        return result
    except Exception:
        return None


@dataclass
class PublicationRunOutcome:
    """Kết quả chạy hoặc resume một Publication."""

    result: ExportResult
    resumed: bool
    seconds: float


def parse_publication(
    corpus_dir: str | Path,
    arxiv_id: str,
    *,
    parse_dir: str | Path | None = None,
    resume: bool = True,
    allow_fallback: bool = False,
    assemble_fn: Callable[[Path], SourceBundle] | None = None,
    structure_fn: Callable[..., tuple[StructureTree, BibSource]] | None = None,
    leaves_fn: Callable[[StructureTree], LeafTree] | None = None,
    bibtex_fn: Callable[[str, list[BibSource]], BibResult] | None = None,
    normalize_fn: Callable[[str, str], str] | None = None,
    module_versions: Mapping[str, str] | None = None,
) -> PublicationRunOutcome:
    """Chạy toàn bộ pipeline M2 cho một Publication (hỗ trợ checkpoint/resume)."""
    t0 = time.perf_counter()
    require_id(arxiv_id)
    corpus = FileCorpus(Path(corpus_dir))
    publication = corpus.read_publication(arxiv_id)
    total_versions = publication.versions

    assembler, structure, leaves, bibtex, normalizer, active_fallbacks = _resolve_stage_functions(
        allow_fallback=allow_fallback,
        assemble_fn=assemble_fn,
        structure_fn=structure_fn,
        leaves_fn=leaves_fn,
        bibtex_fn=bibtex_fn,
        normalize_fn=normalize_fn,
    )
    mod_versions = dict(module_versions or get_module_versions(allow_fallback=allow_fallback))
    input_sha = compute_publication_input_sha256(corpus, arxiv_id, total_versions)

    if parse_dir is not None and resume:
        cached = _load_publication_checkpoint(
            Path(parse_dir), arxiv_id, input_sha, mod_versions, total_versions
        )
        if cached is not None:
            return PublicationRunOutcome(
                result=cached,
                resumed=True,
                seconds=time.perf_counter() - t0,
            )

    version_inputs: list[VersionInput] = []
    bib_sources: list[BibSource] = []

    for ver in range(1, total_versions + 1):
        v_start = time.perf_counter()
        vdir = corpus.version_path(arxiv_id, ver)
        verified = verified_source(vdir)
        if verified is None:
            version_inputs.append(
                VersionInput(
                    version=ver,
                    status="missing",
                    issues=["missing_or_invalid_source"],
                    seconds=time.perf_counter() - v_start,
                )
            )
            continue

        if verified.status == "non_tex":
            sb = assembler(vdir)
            version_inputs.append(
                VersionInput(
                    version=ver,
                    status="empty_non_tex",
                    source_bundle=sb,
                    seconds=time.perf_counter() - v_start,
                )
            )
            continue

        try:
            sb = assembler(vdir)
            if sb.status == "empty_non_tex":
                version_inputs.append(
                    VersionInput(
                        version=ver,
                        status="empty_non_tex",
                        source_bundle=sb,
                        seconds=time.perf_counter() - v_start,
                    )
                )
                continue
            if sb.status != "ready":
                version_inputs.append(
                    VersionInput(
                        version=ver,
                        status="failed",
                        source_bundle=sb,
                        issues=[i.code for i in sb.issues] or ["assemble_failed"],
                        seconds=time.perf_counter() - v_start,
                    )
                )
                continue
            validate_A(sb)
            try:
                st_tree, bib_src = structure(sb, arxiv_id, ver, vdir)
            except TypeError:
                st_tree, bib_src = structure(sb, arxiv_id, ver)
            validate_B(st_tree)
            validate_B_prime(bib_src)
            leaf_tree = leaves(st_tree)
            validate_C(leaf_tree, structure_tree=st_tree)
            bib_sources.append(bib_src)
            version_inputs.append(
                VersionInput(
                    version=ver,
                    status="parsed",
                    leaf_tree=leaf_tree,
                    source_bundle=sb,
                    structure_tree=st_tree,
                    bib_source=bib_src,
                    fallbacks=list(active_fallbacks),
                    seconds=time.perf_counter() - v_start,
                )
            )
        except Exception as exc:
            version_inputs.append(
                VersionInput(
                    version=ver,
                    status="failed",
                    issues=[f"parse_error:{type(exc).__name__}"],
                    fallbacks=list(active_fallbacks),
                    seconds=time.perf_counter() - v_start,
                )
            )

    if bib_sources:
        bib_res = bibtex(arxiv_id, bib_sources)
        validate_D(bib_res, bib_sources=bib_sources)
    else:
        bib_res = BibResult(
            arxiv_id=arxiv_id,
            entries=[],
            key_map={str(v): {} for v in range(1, total_versions + 1)},
            raw_years={},
            stats={
                "entry_before": 0,
                "entry_after": 0,
                "from_bib": 0,
                "from_bibitem": 0,
                "unresolved": 0,
            },
            bibtex_version=mod_versions["bibtex"],
        )

    export_res = export_publication(
        arxiv_id,
        version_inputs,
        bib_res,
        total_versions=total_versions,
        normalize_fn=normalizer,
        include_seconds=False,
        validate_output=True,
    )

    if parse_dir is not None:
        _save_publication_checkpoint(Path(parse_dir), export_res, input_sha, mod_versions)

    return PublicationRunOutcome(
        result=export_res,
        resumed=False,
        seconds=time.perf_counter() - t0,
    )


def run_batch(
    corpus_dir: str | Path,
    out_dir: str | Path,
    *,
    arxiv_ids: Sequence[str] | None = None,
    plan_path: str | Path | None = None,
    metrics_path: str | Path | None = None,
    resume: bool = True,
    allow_fallback: bool = False,
    assemble_fn: Callable[[Path], SourceBundle] | None = None,
    structure_fn: Callable[..., tuple[StructureTree, BibSource]] | None = None,
    leaves_fn: Callable[[StructureTree], LeafTree] | None = None,
    bibtex_fn: Callable[[str, list[BibSource]], BibResult] | None = None,
    normalize_fn: Callable[[str, str], str] | None = None,
) -> dict[str, Any]:
    """Chạy batch trên danh sách Publication hoặc plan, xuất 3 bảng Parquet, log Version và metrics."""
    start_time = time.perf_counter()
    corpus_path = Path(corpus_dir)
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    _, _, _, _, _, active_fallbacks = _resolve_stage_functions(
        allow_fallback=allow_fallback,
        assemble_fn=assemble_fn,
        structure_fn=structure_fn,
        leaves_fn=leaves_fn,
        bibtex_fn=bibtex_fn,
        normalize_fn=normalize_fn,
    )

    plan_seed: int | None = None
    if arxiv_ids is not None:
        target_ids = sorted(set(arxiv_ids))
    elif plan_path is not None:
        plan_data = json.loads(Path(plan_path).read_text(encoding="utf-8"))
        plan_seed = plan_data.get("seed")
        target_ids = sorted(p["arxiv_id"] for p in plan_data["publications"])
    else:
        meta_dir = corpus_path / "metadata"
        target_ids = sorted(
            json.loads(p.read_text(encoding="utf-8"))["publication"]["arxiv_id"]
            for p in sorted(meta_dir.glob("*.json"))
        )

    mod_versions = get_module_versions(allow_fallback=allow_fallback)
    results: list[ExportResult] = []
    resumed_count = 0
    pub_parsed_count = 0
    pub_failed_count = 0

    for aid in target_ids:
        outcome = parse_publication(
            corpus_path,
            aid,
            parse_dir=out_path,
            resume=resume,
            allow_fallback=allow_fallback,
            assemble_fn=assemble_fn,
            structure_fn=structure_fn,
            leaves_fn=leaves_fn,
            bibtex_fn=bibtex_fn,
            normalize_fn=normalize_fn,
            module_versions=mod_versions,
        )
        res = outcome.result
        results.append(res)
        if outcome.resumed:
            resumed_count += 1
        if res.stats["versions_failed"] == 0 and res.stats["versions_missing"] == 0:
            pub_parsed_count += 1
        else:
            pub_failed_count += 1

    tables = merge_export_tables(results)
    tables_dir = out_path / "tables"
    write_export_tables(tables, tables_dir)

    log_path = out_path / "log" / "versions.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    all_logs: list[dict[str, Any]] = []
    for res in results:
        all_logs.extend(res.version_logs)
    log_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in all_logs),
        encoding="utf-8",
    )

    status_counts = Counter(row["status"] for row in all_logs)
    v_total = len(all_logs)
    v_parsed = status_counts["parsed"]
    v_non_tex = status_counts["empty_non_tex"]
    v_failed = status_counts["failed"]
    v_missing = status_counts["missing"]
    tex_versions = v_total - v_non_tex

    elem_before = sum(r.stats["elements_before_dedup"] for r in results)
    elem_after = sum(r.stats["elements_after_dedup"] for r in results)
    bib_before = sum(r.stats["bibtex_before_dedup"] for r in results)
    bib_after = sum(r.stats["bibtex_after_dedup"] for r in results)
    dup_edges = sum(r.stats["duplicate_sibling_edges"] for r in results)

    elapsed = time.perf_counter() - start_time
    n_pubs = len(target_ids)
    git_commit: str | None = None
    try:
        import subprocess

        git_commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).resolve().parents[2],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        git_commit = None

    metrics: dict[str, Any] = {
        "module": "export",
        "git_commit": git_commit,
        "seed": plan_seed,
        "allow_fallback": allow_fallback,
        "fallback_modules": active_fallbacks,
        "module_versions": mod_versions,
        "publications_total": n_pubs,
        "publications_succeeded": pub_parsed_count,
        "publications_failed": pub_failed_count,
        "publications_resumed": resumed_count,
        "publication_parse_rate": round(pub_parsed_count / n_pubs, 6) if n_pubs else 0.0,
        "versions_total_metadata": v_total,
        "versions_parsed": v_parsed,
        "versions_empty_non_tex": v_non_tex,
        "versions_failed": v_failed,
        "versions_missing": v_missing,
        "version_coverage_rate": round((v_parsed + v_non_tex) / v_total, 6) if v_total else 0.0,
        "version_tex_parse_rate": round(v_parsed / tex_versions, 6) if tex_versions else 1.0,
        "elements_before_dedup": elem_before,
        "elements_after_dedup": elem_after,
        "elements_dedup_saved": elem_before - elem_after,
        "elements_dedup_rate": round(1.0 - (elem_after / elem_before), 6) if elem_before else 0.0,
        "bibtex_entries_before_dedup": bib_before,
        "bibtex_entries_after_dedup": bib_after,
        "bibtex_dedup_saved": bib_before - bib_after,
        "bibtex_dedup_rate": round(1.0 - (bib_after / bib_before), 6) if bib_before else 0.0,
        "hierarchy_edges": tables["hierarchy"].num_rows,
        "duplicate_sibling_edges": dup_edges,
        "elapsed_seconds": round(elapsed, 4),
        "avg_seconds_per_publication": round(elapsed / n_pubs, 4) if n_pubs else 0.0,
        "peak_rss_mb": round(peak_rss_mb() or 0.0, 2),
        "output_dir_size_mb": round(dir_size_mb(out_path), 4),
    }
    if metrics_path is not None:
        write_json(Path(metrics_path), metrics)
    write_json(out_path / "metrics.json", metrics)
    return metrics

"""Pipeline tích hợp M2 (docs/m2-cong-viec.md mục 4.4):
Ghép các gói [A] Source -> [B, B'] Structure & BibSource -> [C] Leaves -> [D] BibTeX -> [E] Export,
hỗ trợ checkpoint/resume theo SHA-256 đầu vào và phiên bản các module, ghi log Version (C4),
lưu thứ tự anh em (C3), xuất 3 bảng Parquet và tổng hợp số liệu báo cáo.
"""

from __future__ import annotations

from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from functools import partial
import hashlib
import inspect
import json
from pathlib import Path
import time
import traceback
from typing import Any, Callable, Mapping, Sequence

from src.common.corpus import FileCorpus, file_digest, verified_source
from src.common.json_io import write_json
from src.common.metrics import dir_size_mb, peak_rss_children_mb, peak_rss_mb
from src.common.schema import publication_key, require_id
from src.parse.bibtex import BIBTEX_VERSION, merge_bibtex
from src.parse.export import (
    EXPORT_VERSION,
    ExportResult,
    VersionInput,
    export_publication,
    merge_export_tables,
    validate_E,
    write_export_tables,
)
from src.parse.bibtex_input import supplement_bibliography
from src.parse.leaves import LEAVES_VERSION, build_leaves
from src.parse.normalize import NORMALIZE_VERSION, normalize
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

PIPELINE_VERSION = "8"


def _short(message: str, limit: int = 300) -> str:
    """First line of a message, cut to ``limit`` characters."""
    text = str(message).strip()
    line = text.splitlines()[0] if text else ""
    return line if len(line) <= limit else line[:limit - 1] + "…"


def _describe(exc: BaseException) -> str:
    """``<module>.<function>: <Type>: <first line>`` of an exception, for versions.jsonl."""
    frames = [f for f in traceback.extract_tb(exc.__traceback__)
              if "/src/" in f.filename.replace("\\", "/")]
    where = f"{Path(frames[-1].filename).stem}.{frames[-1].name}" if frames else "unknown"
    return f"{where}: {type(exc).__name__}: {_short(exc)}"


def _function_version_tag(fn: Callable[..., Any]) -> str:
    """Tạo nhãn phiên bản tất định cho hàm tùy chỉnh truyền vào pipeline."""
    mod = getattr(fn, "__module__", "") or ""
    qual = getattr(fn, "__qualname__", None) or getattr(fn, "__name__", type(fn).__name__)
    return f"custom:{mod}.{qual}" if mod else f"custom:{qual}"


def _structure_accepts_vdir(fn: Callable[..., Any]) -> bool:
    """Kiểm tra bằng inspect.signature xem structure_fn có nhận tham số thứ 4 (vdir) không."""
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return True
    positional = 0
    for param in sig.parameters.values():
        if param.kind == inspect.Parameter.VAR_POSITIONAL:
            return True
        if param.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ):
            positional += 1
    return positional >= 4


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
    dict[str, str],
]:
    """Nạp các gói thật; allow_fallback chỉ giữ tương thích lời gọi cũ."""
    assembler = assemble_fn if assemble_fn is not None else assemble_source
    structure = structure_fn if structure_fn is not None else build_structure
    leaves = leaves_fn if leaves_fn is not None else build_leaves
    active_fallbacks: list[str] = []
    versions: dict[str, str] = {
        "assembler": (
            str(ASSEMBLER_VERSION) if assemble_fn is None else _function_version_tag(assemble_fn)
        ),
        "structure": (
            str(STRUCTURE_VERSION) if structure_fn is None else _function_version_tag(structure_fn)
        ),
        "leaves": (
            str(LEAVES_VERSION) if leaves_fn is None else _function_version_tag(leaves_fn)
        ),
        "types": str(TYPES_VERSION),
        "export": str(EXPORT_VERSION),
        "pipeline": str(PIPELINE_VERSION),
    }

    bibtex = bibtex_fn if bibtex_fn is not None else merge_bibtex
    normalizer = normalize_fn if normalize_fn is not None else normalize
    versions["bibtex"] = (
        str(BIBTEX_VERSION) if bibtex_fn is None else _function_version_tag(bibtex_fn)
    )
    versions["normalize"] = (
        str(NORMALIZE_VERSION) if normalize_fn is None else _function_version_tag(normalize_fn)
    )
    return assembler, structure, leaves, bibtex, normalizer, active_fallbacks, versions


def get_module_versions(*, allow_fallback: bool = False) -> dict[str, str]:
    """Phiên bản gói thật; allow_fallback được giữ để tương thích lời gọi cũ."""
    return _resolve_stage_functions()[-1]


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


def _bibliography_inputs_digest(
    arxiv_id: str,
    total_versions: int,
    supplement_dir: Path | None,
    root_reviews: Mapping[tuple[str, int], Mapping[str, Any]],
) -> str | None:
    """Băm các đầu vào ngoài corpus M1 mà một Publication dùng: sidecar và root đã review.

    Sidecar bibliography (``scripts/recover_bibtex_sources.py``, data-contract mục 4.2) và
    ``configs/m2-reviewed-roots.json`` đổi kết quả parse, nên phải vào khóa checkpoint.
    Trả ``None`` khi Publication không dùng đầu vào nào như vậy (khóa giữ như cũ).
    """
    parts: list[str] = []
    for ver in range(1, total_versions + 1):
        if supplement_dir is not None:
            manifest = supplement_dir / publication_key(arxiv_id) / f"v{ver}" / "manifest.json"
            if manifest.is_file():
                parts.append(f"supplement:v{ver}:{file_digest(manifest)}")
        review = root_reviews.get((arxiv_id, ver))
        if review is not None:
            parts.append(
                f"root:v{ver}:{review['root_file']}:{review['root_sha256']}:{review['receipt_sha256']}"
            )
    if not parts:
        return None
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def _assemble_reviewed_root(vdir: Path, review: Mapping[str, Any]) -> SourceBundle:
    """Gom Version theo file gốc đã review, sau khi kiểm receipt và file gốc chưa đổi."""
    if (file_digest(vdir / "source.json") != review["receipt_sha256"]
            or file_digest(vdir / review["root_file"]) != review["root_sha256"]):
        raise ValueError("root review không còn khớp receipt/file gốc")
    return assemble_source(vdir, root_file=review["root_file"], require_receipt=True)


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
            "unresolved_keys": sorted(result.unresolved_keys),
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
            unresolved_keys=frozenset(cached.get("unresolved_keys", [])),
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
    supplement_dir: str | Path | None = None,
    root_reviews: Mapping[tuple[str, int], Mapping[str, Any]] | None = None,
) -> PublicationRunOutcome:
    """Chạy toàn bộ pipeline M2 cho một Publication (hỗ trợ checkpoint/resume).

    ``supplement_dir``: thư mục sidecar bibliography do ``scripts/recover_bibtex_sources.py`` tạo.
    Version có ``<key>/v<n>/manifest.json`` được bổ sung ``.bib/.bbl`` mà M1 đã lọc mất
    (``supplement_bibliography``), log Version ghi ``bibliography_recovered``.
    ``root_reviews``: kết quả ``load_root_reviews(configs/m2-reviewed-roots.json)``; Version có
    review được gom theo file gốc đã chọn thay vì báo ``ambiguous_root``. Chỉ áp dụng khi dùng
    bộ gom mặc định (``assemble_fn is None``).
    """
    t0 = time.perf_counter()
    require_id(arxiv_id)
    corpus = FileCorpus(Path(corpus_dir))
    publication = corpus.read_publication(arxiv_id)
    total_versions = publication.versions

    (
        assembler,
        structure,
        leaves,
        bibtex,
        normalizer,
        active_fallbacks,
        resolved_versions,
    ) = _resolve_stage_functions(
        allow_fallback=allow_fallback,
        assemble_fn=assemble_fn,
        structure_fn=structure_fn,
        leaves_fn=leaves_fn,
        bibtex_fn=bibtex_fn,
        normalize_fn=normalize_fn,
    )
    mod_versions = dict(module_versions) if module_versions is not None else dict(resolved_versions)
    supplement_path = Path(supplement_dir) if supplement_dir is not None else None
    reviews = root_reviews or {}
    input_sha = compute_publication_input_sha256(corpus, arxiv_id, total_versions)
    extra_inputs = _bibliography_inputs_digest(arxiv_id, total_versions, supplement_path, reviews)
    if extra_inputs is not None:
        input_sha = hashlib.sha256(f"{input_sha}:{extra_inputs}".encode("utf-8")).hexdigest()

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

    structure_wants_vdir = _structure_accepts_vdir(structure)
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
                    fallbacks=list(active_fallbacks),
                    seconds=time.perf_counter() - v_start,
                )
            )
            continue

        if verified.status in ("non_tex", "unavailable"):
            empty_status = "empty_non_tex" if verified.status == "non_tex" else "empty_unavailable"
            try:
                sb = assembler(vdir)
                version_inputs.append(
                    VersionInput(
                        version=ver,
                        status=empty_status,
                        source_bundle=sb,
                        fallbacks=list(active_fallbacks),
                        seconds=time.perf_counter() - v_start,
                    )
                )
            except Exception as exc:
                version_inputs.append(
                    VersionInput(
                        version=ver,
                        status="failed",
                        issues=[f"assemble_error:{type(exc).__name__}"],
                        fallbacks=list(active_fallbacks),
                        seconds=time.perf_counter() - v_start,
                        error=_describe(exc),
                    )
                )
            continue

        try:
            review = reviews.get((arxiv_id, ver)) if assemble_fn is None else None
            if review is not None:
                sb = _assemble_reviewed_root(vdir, review)
            elif assemble_fn is None:
                # The metadata title is evidence for choosing among several roots
                # (ADR 0005); metadata is already part of the checkpoint input hash.
                sb = assembler(vdir, title_hint=publication.title)
            else:
                sb = assembler(vdir)
            if sb.status in ("empty_non_tex", "empty_unavailable"):
                version_inputs.append(
                    VersionInput(
                        version=ver,
                        status=sb.status,
                        source_bundle=sb,
                        fallbacks=list(active_fallbacks),
                        seconds=time.perf_counter() - v_start,
                    )
                )
                continue
            if sb.status not in ("ready", "needs_review"):
                version_inputs.append(
                    VersionInput(
                        version=ver,
                        status="failed",
                        source_bundle=sb,
                        issues=[i.code for i in sb.issues] or ["assemble_failed"],
                        fallbacks=list(active_fallbacks),
                        seconds=time.perf_counter() - v_start,
                        error=next((f"assemble: {i.code}: {_short(i.message)}" for i in sb.issues
                                    if i.severity == "error"), None),
                    )
                )
                continue
            validate_A(sb)
            if structure_wants_vdir:
                st_tree, bib_src = structure(sb, arxiv_id, ver, vdir)
            else:
                st_tree, bib_src = structure(sb, arxiv_id, ver)
            validate_B(st_tree)
            # Keep rule-based root choices auditable in log/versions.jsonl (ADR 0005).
            extra_issues: list[str] = [
                i.code for i in sb.issues
                if i.code in ("root_selected_by_title", "root_selected_by_name")
            ]
            if supplement_path is not None:
                manifest = supplement_path / publication_key(arxiv_id) / f"v{ver}" / "manifest.json"
                if manifest.is_file():
                    bib_src, _ = supplement_bibliography(bib_src, sb, vdir, manifest)
                    extra_issues.append("bibliography_recovered")
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
                    issues=extra_issues,
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
                    error=_describe(exc),
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
        allow_fallback=allow_fallback,
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


def _failed_publication_result(
    corpus: FileCorpus,
    arxiv_id: str,
    exc: Exception,
    active_fallbacks: Sequence[str],
) -> ExportResult:
    """Tạo ExportResult đánh dấu mọi Version là failed khi một Publication ném lỗi ở run_batch."""
    issues = [f"publication_error:{type(exc).__name__}"]
    try:
        total_versions = max(1, int(corpus.read_publication(arxiv_id).versions))
    except Exception:
        total_versions = 1
        issues.append("metadata_unreadable")

    version_logs: list[dict[str, Any]] = []
    for ver in range(1, total_versions + 1):
        row: dict[str, Any] = {
            "arxiv_id": arxiv_id,
            "version": ver,
            "status": "failed",
            "issues": list(issues),
            "elements": 0,
            "edges": 0,
            "duplicate_sibling_edges": 0,
            "no_bibliography": False,
            "error": _describe(exc),
        }
        if active_fallbacks:
            row["fallbacks"] = sorted(set(active_fallbacks))
        version_logs.append(row)

    return ExportResult(
        arxiv_id=arxiv_id,
        elements=[],
        hierarchy=[],
        bibtex=[],
        version_logs=version_logs,
        order={},
        stats={
            "versions_total": total_versions,
            "versions_parsed": 0,
            "versions_non_tex": 0,
            "versions_unavailable": 0,
            "versions_failed": total_versions,
            "versions_missing": 0,
            "elements_before_dedup": 0,
            "elements_after_dedup": 0,
            "bibtex_before_dedup": 0,
            "bibtex_after_dedup": 0,
            "bibtex_unresolved_keys": 0,
            "duplicate_sibling_edges": 0,
        },
        root_by_version={},
    )


def _chunksize(n_tasks: int, workers: int) -> int:
    """Lô nhỏ để cân tải (Publication dài ngắn rất khác nhau) mà vẫn giảm chi phí gửi task."""
    return max(1, min(16, n_tasks // (workers * 8)))


def _parse_one_publication(
    corpus_path: Path,
    active_fallbacks: Sequence[str],
    stage_options: Mapping[str, Any],
    arxiv_id: str,
) -> tuple[ExportResult, bool]:
    """Parse một Publication cho run_batch; lỗi được đổi thành ExportResult failed, không ném ra.

    Ở cấp module để ProcessPoolExecutor pickle được.
    """
    try:
        outcome = parse_publication(corpus_path, arxiv_id, **stage_options)
        return outcome.result, outcome.resumed
    except Exception as exc:
        return _failed_publication_result(FileCorpus(corpus_path), arxiv_id, exc, active_fallbacks), False


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
    supplement_dir: str | Path | None = None,
    root_reviews: Mapping[tuple[str, int], Mapping[str, Any]] | None = None,
    workers: int = 1,
) -> dict[str, Any]:
    """Chạy batch trên danh sách Publication hoặc plan, xuất 3 bảng Parquet, log Version và metrics.

    ``supplement_dir`` và ``root_reviews``: xem ``parse_publication``.
    ``workers``: số tiến trình parse song song theo Publication (1 = tuần tự). Bảng xuất ra giống
    hệt bản tuần tự vì kết quả được gộp theo thứ tự ID. Khi ``workers > 1``, các hàm Stage tùy
    chỉnh phải pickle được (hàm cấp module).
    """
    if workers < 1:
        raise ValueError(f"workers phải >= 1, nhận {workers}")
    start_time = time.perf_counter()
    corpus_path = Path(corpus_dir)
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    _, _, _, _, _, active_fallbacks, mod_versions = _resolve_stage_functions(
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

    stage_options: dict[str, Any] = {
        "parse_dir": out_path,
        "resume": resume,
        "assemble_fn": assemble_fn,
        "structure_fn": structure_fn,
        "leaves_fn": leaves_fn,
        "bibtex_fn": bibtex_fn,
        "normalize_fn": normalize_fn,
        "module_versions": mod_versions,
        "supplement_dir": supplement_dir,
        "root_reviews": root_reviews,
    }
    parse_one = partial(_parse_one_publication, corpus_path, active_fallbacks, stage_options)
    if workers > 1 and len(target_ids) > 1:
        # Mỗi Publication độc lập và có checkpoint riêng, nên chia cho nhiều tiến trình được.
        # executor.map trả kết quả theo đúng thứ tự target_ids, nên bảng gộp giống hệt bản tuần tự.
        with ProcessPoolExecutor(max_workers=min(workers, len(target_ids))) as pool:
            outcomes = list(pool.map(parse_one, target_ids, chunksize=_chunksize(len(target_ids), workers)))
        # Đo ngay sau khi pool đóng, trước lệnh `git rev-parse` ở dưới (cũng là tiến trình con).
        children_peak_mb = peak_rss_children_mb() or 0.0
    else:
        outcomes = [parse_one(aid) for aid in target_ids]
        children_peak_mb = 0.0

    results: list[ExportResult] = []
    resumed_count = 0
    pub_parsed_count = 0
    pub_empty_only_count = 0
    pub_failed_count = 0
    for res, resumed in outcomes:
        resumed_count += resumed
        results.append(res)
        if res.stats["versions_failed"] == 0 and res.stats["versions_missing"] == 0:
            pub_parsed_count += 1
            if res.stats["versions_parsed"] == 0:
                pub_empty_only_count += 1
        else:
            pub_failed_count += 1
    del outcomes

    tables = merge_export_tables(results)
    tables_dir = out_path / "tables"
    write_export_tables(tables, tables_dir)

    log_path = out_path / "log" / "versions.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    all_logs: list[dict[str, Any]] = []
    for res in results:
        all_logs.extend(res.version_logs)
    log_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in all_logs),
        encoding="utf-8",
    )

    status_counts = Counter(row["status"] for row in all_logs)
    v_total = len(all_logs)
    v_parsed = status_counts["parsed"]
    v_non_tex = status_counts["empty_non_tex"]
    v_unavailable = status_counts["empty_unavailable"]
    v_empty = v_non_tex + v_unavailable
    v_failed = status_counts["failed"]
    v_missing = status_counts["missing"]
    tex_versions = v_total - v_empty

    elem_before = sum(r.stats["elements_before_dedup"] for r in results)
    elem_after = sum(r.stats["elements_after_dedup"] for r in results)
    bib_before = sum(r.stats["bibtex_before_dedup"] for r in results)
    bib_after = sum(r.stats["bibtex_after_dedup"] for r in results)
    bib_unresolved = sum(r.stats.get("bibtex_unresolved_keys", 0) for r in results)
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
        "allow_fallback": False,
        "bibliography_supplement": supplement_dir is not None,
        "root_reviews": len(root_reviews or {}),
        "versions_bibliography_recovered": sum(
            "bibliography_recovered" in log.get("issues", [])
            for r in results for log in r.version_logs
        ),
        "fallback_modules": active_fallbacks,
        "module_versions": mod_versions,
        "publications_total": n_pubs,
        "publications_succeeded": pub_parsed_count,
        "publications_empty_only": pub_empty_only_count,
        "publications_failed": pub_failed_count,
        "publications_resumed": resumed_count,
        "publication_parse_rate": round(pub_parsed_count / n_pubs, 6) if n_pubs else 0.0,
        "versions_total_metadata": v_total,
        "versions_parsed": v_parsed,
        "versions_empty_non_tex": v_non_tex,
        "versions_empty_unavailable": v_unavailable,
        "versions_failed": v_failed,
        "versions_missing": v_missing,
        "version_coverage_rate": round((v_parsed + v_empty) / v_total, 6) if v_total else 0.0,
        "version_tex_parse_rate": round(v_parsed / tex_versions, 6) if tex_versions else 1.0,
        "elements_before_dedup": elem_before,
        "elements_after_dedup": elem_after,
        "elements_dedup_saved": elem_before - elem_after,
        "elements_dedup_rate": round(1.0 - (elem_after / elem_before), 6) if elem_before else 0.0,
        "bibtex_entries_before_dedup": bib_before,
        "bibtex_entries_after_dedup": bib_after,
        "bibtex_dedup_saved": bib_before - bib_after,
        "bibtex_unresolved_keys": bib_unresolved,
        "bibtex_dedup_rate": round(1.0 - (bib_after / bib_before), 6) if bib_before else 0.0,
        "hierarchy_edges": tables["hierarchy"].num_rows,
        "duplicate_sibling_edges": dup_edges,
        "elapsed_seconds": round(elapsed, 4),
        "avg_seconds_per_publication": round(elapsed / n_pubs, 4) if n_pubs else 0.0,
        "workers": workers,
        "peak_rss_mb": round(peak_rss_mb() or 0.0, 2),
        # Đỉnh RAM của tiến trình con lớn nhất (0 khi chạy tuần tự); RAM đỉnh toàn máy có thể tới
        # peak_rss_mb + workers * peak_rss_children_mb.
        "peak_rss_children_mb": round(children_peak_mb, 2),
        "tables_dir_size_mb": round(dir_size_mb(tables_dir), 4),
        "output_dir_size_mb": round(dir_size_mb(out_path), 4),
    }
    if metrics_path is not None:
        write_json(Path(metrics_path), metrics)
    write_json(out_path / "metrics.json", metrics)
    return metrics

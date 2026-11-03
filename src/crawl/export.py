"""Export complete, verified Publications into the existing batch tables.

The caller holds the corpus lock. This module never crawls or uploads data.
"""
from dataclasses import asdict
from pathlib import Path
from typing import TypedDict
from src.common.schema import from_records, write_table
from .corpus import CorpusReader
from .discovery import Publication
from .source import verified_source, SourceResult
from .semantic_scholar import reference_rows
from .storage import key


class PublicationBundle(TypedDict):
    """Validated local inputs consumed by the Hugging Face publisher."""
    publication: Publication
    sources: list[SourceResult]
    metadata: Path
    references: Path | None


def export_publications(corpus: CorpusReader, source_root: Path, ids: list[str], *,
                        require_references: bool = True) -> tuple[list[PublicationBundle], dict[str, Path]]:
    """Write only complete Publications; preserve the existing batch semantics."""
    bundles, papers, references = [], [], []
    for arxiv_id in dict.fromkeys(ids):
        try:
            record = corpus.manifest.get(arxiv_id, None, "discovery")
            if not record or record.status != "success":
                continue
            publication = corpus.load_publication(arxiv_id)
            sources = []
            for version in range(1, publication.versions + 1):
                task = corpus.manifest.get(arxiv_id, version)
                if not task or task.status not in {"success", "non_tex"}:
                    raise ValueError("Incomplete source coverage")
                source = verified_source(source_root / key(arxiv_id) / f"v{version}")
                if not source or source.checksum != task.checksum:
                    raise ValueError("Source checksum mismatch")
                sources.append(source)
            raw_refs = corpus.load_references(arxiv_id) if require_references else None
            row = asdict(publication)
            row.pop("versions")
            papers.append(row)
            if raw_refs is not None:
                references.extend(reference_rows(arxiv_id, raw_refs))
            bundles.append({"publication": publication, "sources": sources,
                            "metadata": corpus.metadata_path(arxiv_id),
                            "references": corpus.references_path(arxiv_id) if raw_refs is not None else None})
        except (OSError, ValueError, KeyError, TypeError):
            continue
    paths = {}
    for name, rows in (("papers", papers), ("references", references)):
        if name == "references" and not require_references:
            continue
        path = corpus.data_dir / "tables" / f"{name}.parquet"
        write_table(from_records(rows, name), name, path)
        paths[name] = path
    return bundles, paths

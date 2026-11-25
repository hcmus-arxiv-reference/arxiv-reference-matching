"""Export complete, verified Publications into the existing batch tables.

The caller holds the corpus lock. This module never crawls or uploads data.
"""
from dataclasses import asdict
from pathlib import Path
from typing import TypedDict
from src.common.schema import from_records, write_table
from .corpus import CorpusReader
from .discovery import Publication
from .source import SourceResult


class PublicationBundle(TypedDict):
    """Validated local inputs consumed by the Hugging Face publisher."""
    publication: Publication
    sources: list[SourceResult]
    metadata: Path
    references: Path | None


def export_publications(corpus: CorpusReader, source_root: Path, ids: list[str], *,
                        require_references: bool = True,
                        include_incomplete: bool = False) -> tuple[list[PublicationBundle], dict[str, Path]]:
    """Write only complete Publications; preserve the existing batch semantics.

    ``include_incomplete``: also write the ``papers`` row (and ``references`` rows when the
    references cache is valid) of a Publication whose metadata is valid but some Version is not
    verified yet, e.g. an archive that failed to download. Such a Publication gets no bundle, so
    its unverified files are never uploaded; the missing Version stays visible in the M2 Version
    log as ``missing``, and a later crawl that verifies it needs no change here.
    """
    bundles, papers, references = [], [], []
    reader = CorpusReader(corpus.data_dir, corpus.manifest, source_root)
    for arxiv_id in dict.fromkeys(ids):
        try:
            state = reader.status(arxiv_id)
            if not (state.complete if require_references else state.sources_complete):
                if include_incomplete and state.publication is not None:
                    row = asdict(state.publication)
                    row.pop("versions")
                    papers.append(row)
                    if require_references and state.references is not None:
                        references.extend(state.references.references)
                continue
            publication, sources = state.publication, state.sources()
            citations = state.references if require_references else None
            row = asdict(publication)
            row.pop("versions")
            papers.append(row)
            if citations is not None:
                references.extend(citations.references)
            bundles.append({"publication": publication, "sources": sources,
                            "metadata": corpus.metadata_path(arxiv_id),
                            "references": corpus.references_path(arxiv_id) if citations is not None else None})
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

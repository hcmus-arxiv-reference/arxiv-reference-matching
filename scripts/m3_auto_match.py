"""M3: evaluate a classical reference matcher and generate team-wide automatic labels."""

import argparse
import csv
import json
import math
import random
import re
import subprocess
import sys
import tempfile
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow.parquet as pq
from rapidfuzz.distance import Levenshtein

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.m3_check_labels import LABEL_COLUMNS, check
from src.common.config import get_settings, load_ranges
from src.common.hf_io import download_dir, table_path
from src.common.schema import publication_key

SEED = 20261120
ID_PATTERN = re.compile(
    r"(?:\barxiv\s*:\s*|arxiv\.org/(?:abs|pdf)/|10\.48550/arxiv\.)"
    r"(\d{4}\.\d{4,5}|[a-z][a-z.-]*/\d{7})(?:v\d+)?(?!\w)",
    re.I,
)


def read_csv(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path, columns, rows):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def row_key(row):
    return row["arxiv_id"], row["citation_key"]


def normalize(text):
    text = re.sub(r"\\(?:emph|textit|textbf|mathrm)\b", "", text or "")
    text = re.sub(r"""\\["'`^~=.]\s*\{?(\w)\}?""", r"\1", text)
    text = unicodedata.normalize("NFKD", text.casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(re.findall(r"[^\W_]+", text))


def surnames(authors):
    names = set()
    for author in authors or []:
        words = normalize(author.split(",")[0]).split()
        if words:
            names.add(words[-1])
    return names


def candidate(row):
    return (
        normalize(row.get("ref_title")),
        surnames(row.get("ref_authors")),
        str(row.get("ref_submission_date") or "")[:4],
    )


def match(entry, candidates):
    """Return ref_arxiv_id, confidence, reason and heuristic score."""
    evidence = " ".join(str(entry.get(k) or "") for k in ("url", "doi", "journal", "title"))
    ids = {m.casefold() for m in ID_PATTERN.findall(evidence)}
    if len(ids) > 1:
        return "", "unsure", "conflicting_ids", 0.0
    if ids:
        rid = next(iter(ids))
        if rid in candidates:
            return rid, "sure", "explicit_id", 1.0
        return "", "sure", "id_outside_candidates", 0.0

    title = normalize(entry.get("title"))
    if not candidates:
        return "", "sure", "no_candidates", 0.0
    if not title:
        return "", "unsure", "missing_title", 0.0

    authors = surnames(entry.get("authors"))
    year = str(entry.get("year") or "")
    ranked = []
    for rid, (other_title, other_authors, other_year) in candidates.items():
        if not other_title:
            continue
        common_authors = authors & other_authors
        if min(len(title.split()), len(other_title.split())) < 3 and not common_authors:
            continue
        similarity = Levenshtein.normalized_similarity(title, other_title)
        score = similarity
        if authors and other_authors:
            score += 0.025 if common_authors else -0.09
        if year.isdigit() and other_year.isdigit():
            score += 0.01 if abs(int(year) - int(other_year)) <= 1 else -0.025
        ranked.append((score, similarity, rid))

    if not ranked:
        return "", "unsure", "insufficient_evidence", 0.0
    ranked.sort(reverse=True)
    best, similarity, rid = ranked[0]
    score = round(max(0.0, min(1.0, best)), 4)
    if similarity < 0.90 or best < 0.93:
        return "", "unsure", "below_threshold", score
    if len(ranked) > 1 and best - ranked[1][0] < 0.035:
        return "", "unsure", "ambiguous", score
    return rid, "sure", "title_match", score


def load_gold(files):
    rows = [r for path in files for r in read_csv(path)]
    if not rows:
        raise ValueError("Chưa có CSV nhãn tay.")
    errors, _ = check(rows, list(rows[0]), None)
    if errors:
        raise ValueError("\n".join(errors[:10]))
    return {row_key(r): r["ref_arxiv_id"] for r in rows}


def publication_key_map(pid, directory):
    """Rebuild M2's aliases for the TeX version used by the manual sheet."""
    from scripts.m3_label_sheet import newest_tex_version
    from src.parse.bibtex import merge_bibtex
    from src.parse.source import assemble_source
    from src.parse.structure import build_structure

    latest = newest_tex_version(directory)
    if latest is None:
        raise ValueError(f"{pid}: thiếu nguồn TeX để đối chiếu citation_key.")
    sources = []
    for folder in sorted(directory.glob("v*")):
        if not folder.is_dir() or not folder.name[1:].isdigit():
            continue
        bundle = assemble_source(folder, require_receipt=True)
        if bundle.status in {"ready", "needs_review"}:
            _, bib = build_structure(bundle, pid, int(folder.name[1:]), folder)
            sources.append(bib)
    result = merge_bibtex(pid, sources)
    return result.key_map.get(str(latest[0]), {})


def align_gold(gold, entries, get_map):
    """Resolve missing manual keys and count agreeing aliases only once."""
    affected = {pid for pid, cite in gold if (pid, cite) not in entries}
    maps = {pid: get_map(pid) for pid in sorted(affected)}
    aligned = {}
    for (pid, cite), truth in gold.items():
        target = maps.get(pid, {}).get(cite, cite)
        key = (pid, target)
        if key not in entries:
            raise ValueError(f"Thiếu khóa bibtex {pid}/{cite} sau khi đối chiếu key_map: {target}")
        if key in aligned and aligned[key] != truth:
            raise ValueError(f"Nhãn tay mâu thuẫn sau khi gộp {pid}/{target}.")
        aligned[key] = truth
    return aligned


def evaluate(gold, entries, refs, output):
    details = []
    tp = fp = fn = tn = 0
    for key, truth in sorted(gold.items()):
        pid, cite = key
        if key not in entries:
            raise ValueError(f"Thiếu khóa bibtex {pid}/{cite}. Kiểm tra key_map của M2.")
        if truth and truth not in refs.get(pid, {}):
            raise ValueError(f"Nhãn tay {pid}/{cite}: {truth} không thuộc references của bài.")
        pred, _, reason, score = match(entries[key], refs.get(pid, {}))
        tp += bool(truth and pred == truth)
        fp += bool(pred and pred != truth)
        fn += bool(truth and pred != truth)
        tn += not truth and not pred
        details.append(dict(arxiv_id=pid, citation_key=cite, gold=truth,
                            predicted=pred, reason=reason, score=score))
    write_csv(output / "manual-eval.csv",
              ["arxiv_id", "citation_key", "gold", "predicted", "reason", "score"], details)
    return dict(entries=len(details), tp=tp, fp=fp, fn=fn, tn=tn,
                precision=tp/(tp+fp) if tp+fp else None,
                recall=tp/(tp+fn) if tp+fn else None)


def bib_field(text, name):
    """Read a field from a possibly truncated BibTeX excerpt."""
    found = re.search(r"\b" + name + r'\s*=\s*([{"])', text, re.I)
    if not found:
        return ""
    depth = 1
    for i in range(found.end(), len(text)):
        char = text[i]
        if found[1] == '"':
            if char == '"' and text[i-1] != "\\":
                return text[found.end():i]
        else:
            depth += (char == "{") - (char == "}")
            if depth == 0:
                return text[found.end():i]
    return ""


def pilot(sheet, labels, output):
    from src.parse.bibtex import _bibitem_parts

    gold = load_gold([labels])
    rows = read_csv(sheet)
    if len(rows) != len(gold) or {row_key(r) for r in rows} != set(gold):
        raise ValueError("Các khóa trong phiếu và CSV nhãn tay không khớp.")
    entries, refs = {}, {}
    for row in rows:
        pid, cite = row_key(row)
        if pid not in refs:
            refs[pid] = {}
            filename = pid.replace(".", "-").replace("/", "-") + ".csv"
            for ref in read_csv(sheet.parent / "candidates" / filename):
                ref["ref_authors"] = [s.strip() for s in (ref.get("ref_authors") or "").split(";")
                                      if s.strip()]
                refs[pid][ref["ref_arxiv_id"]] = candidate(ref)
        raw = row["entry"]
        if raw.lstrip().startswith("@"):
            title = bib_field(raw, "title")
            authors = re.split(r"\s+and\s+", bib_field(raw, "author"), flags=re.I)
        else:
            title, authors = _bibitem_parts(raw)
        entries[pid, cite] = dict(title=title, authors=authors, year=bib_field(raw, "year"), url=raw)
    return dict(mode="pilot", publications=len(refs),
                metrics=evaluate(gold, entries, refs, output))


def load_ids(path):
    return set(pq.read_table(path, columns=["arxiv_id"]).column(0).unique().to_pylist())


def selected_rows(path, ids, columns):
    if not ids:
        return []
    return pq.read_table(path, columns=columns,
                         filters=[("arxiv_id", "in", sorted(ids))]).to_pylist()


def team(output):
    from huggingface_hub import HfApi, hf_hub_download

    settings = get_settings()
    settings.require_hf()
    repo = settings.hf_repo_id
    api = HfApi(token=settings.hf_token)
    revision = api.dataset_info(repo).sha
    members = load_ranges()

    def download(name):
        return Path(hf_hub_download(repo_id=repo, filename=name, repo_type="dataset",
                                    revision=revision, token=settings.hf_token))

    label_files = sorted(obj.path for obj in api.list_repo_tree(
        repo, "labels/manual", repo_type="dataset", revision=revision)
        if obj.path.endswith(".csv"))
    gold = load_gold([download(name) for name in label_files])
    manual = {pid for pid, _ in gold}
    needed = {table_path(m, t) for m in members for t in ("papers", "bibtex", "references")}
    present = {obj.path for obj in api.get_paths_info(
        repo, sorted(needed | {"labels/splits.csv"}), repo_type="dataset", revision=revision)}
    missing = sorted(needed - present)
    incomplete = [m for m, info in members.items()
                  if sum(pid in info.range for pid in manual) < 5]
    if missing or incomplete:
        raise ValueError(f"Thiếu bảng: {missing}\nRange chưa đủ 5 bài tay: {incomplete}")

    evaluation = gold
    eval_pool = "all manual before split"
    if "labels/splits.csv" in present:
        split = {}
        for row in read_csv(download("labels/splits.csv")):
            if row["pool"] != "manual":
                continue
            pid = row["arxiv_id"]
            if pid in split or row["partition"] not in {"train", "valid", "test"}:
                raise ValueError(f"Split manual không hợp lệ cho {pid}")
            split[pid] = row["partition"]
        if set(split) != manual:
            raise ValueError("splits.csv không phủ đúng các bài manual.")
        evaluation = {k: v for k, v in gold.items() if split[k[0]] == "train"}
        if not evaluation:
            raise ValueError("Không có nhãn manual/train để đánh giá.")
        eval_pool = "manual/train"

    owners, with_entries, paths = {}, set(), {}
    for m in members:
        paths[m] = {t: download(table_path(m, t)) for t in ("papers", "bibtex", "references")}
        ids = load_ids(paths[m]["papers"])
        bib_ids = load_ids(paths[m]["bibtex"])
        if owners.keys() & ids or bib_ids - ids:
            raise ValueError(f"{m}: kiểm tra bài trùng Range hoặc bibtex ngoài papers.")
        owners.update(dict.fromkeys(ids, m))
        with_entries.update(bib_ids)
    if manual - owners.keys():
        raise ValueError("Có bài manual không nằm trong bảng papers.")

    remaining = set(owners) - manual
    required = max(2 * len(members), math.ceil(len(remaining) / 10))
    available = sorted(remaining & with_entries)
    if len(available) < required:
        raise ValueError(f"Cần {required} bài auto nhưng chỉ {len(available)} bài có entry M2.")
    selected = set(random.Random(SEED).sample(available, required))

    entries, refs = {}, defaultdict(dict)
    for m in members:
        ids = {pid for pid in selected | manual if owners[pid] == m}
        for row in selected_rows(paths[m]["bibtex"], ids,
                                 ["arxiv_id", "citation_key", "title", "authors",
                                  "year", "doi", "url", "journal"]):
            key = row_key(row)
            if not key[1] or key in entries:
                raise ValueError(f"Khóa bibtex trống hoặc trùng: {key}")
            entries[key] = row
        for row in selected_rows(paths[m]["references"], ids,
                                 ["arxiv_id", "ref_arxiv_id", "ref_title",
                                  "ref_authors", "ref_submission_date"]):
            pid, rid = row["arxiv_id"], row["ref_arxiv_id"]
            if rid in refs[pid]:
                raise ValueError(f"Trùng reference {pid}/{rid}")
            refs[pid][rid] = candidate(row)

    manual_rows = len(evaluation)
    with tempfile.TemporaryDirectory() as cache:
        def get_map(pid):
            remote = f"raw/{owners[pid]}/{publication_key(pid)}"
            directory = download_dir(settings, remote, cache, revision=revision)
            return publication_key_map(pid, directory)

        evaluation = align_gold(evaluation, entries, get_map)
    metrics = evaluate(evaluation, entries, refs, output)
    metrics["manual_rows"] = manual_rows
    metrics["merged_alias_rows"] = manual_rows - len(evaluation)
    print("Precision/recall trên nhãn tay:", metrics, flush=True)
    subprocess.run(["git", "ls-files", "--error-unmatch", "scripts/m3_auto_match.py"],
                   cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    subprocess.run(["git", "diff", "--quiet", "HEAD", "--", "scripts/m3_auto_match.py"],
                   cwd=ROOT, check=True)
    commit = subprocess.check_output(["git", "rev-parse", "--short=12", "HEAD"],
                                     cwd=ROOT, text=True).strip()
    labeler = "matcher@" + commit
    counts = Counter()
    with (output / "auto.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=LABEL_COLUMNS + ["score"])
        writer.writeheader()
        for (pid, cite), entry in sorted(entries.items()):
            if pid not in selected:
                continue
            rid, confidence, reason, score = match(entry, refs[pid])
            counts[reason] += 1
            writer.writerow(dict(arxiv_id=pid, citation_key=cite, ref_arxiv_id=rid,
                                 confidence=confidence, labeler=labeler, note=reason, score=score))
    return dict(mode="team", dataset_revision=revision, labeler=labeler, seed=SEED,
                manual_publications=len(manual), remaining_publications=len(remaining),
                remaining_with_entries=len(available), auto_publications=len(selected),
                auto_entries=sum(counts.values()), evaluation_pool=eval_pool, metrics=metrics,
                reasons=dict(counts), selected=sorted(selected))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--pilot-sheet", type=Path)
    modes.add_argument("--hf", action="store_true")
    parser.add_argument("--labels", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.pilot_sheet and not args.labels:
        parser.error("--pilot-sheet cần --labels")
    if args.out.exists():
        parser.error(f"{args.out} đã tồn tại. Dùng thư mục --out mới.")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=args.out.parent) as tmp:
        output = Path(tmp) / "result"
        output.mkdir()
        report = pilot(args.pilot_sheet, args.labels, output) if args.pilot_sheet else team(output)
        (output / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        output.rename(args.out)
    print("Đã ghi", args.out)
    print("Kết quả:", report["metrics"])


if __name__ == "__main__":
    main()

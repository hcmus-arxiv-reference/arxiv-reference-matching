"""Check literal bibliography inputs before merging across Versions."""
import pytest

from src.parse.bibtex import _bib_candidates, _bibitem_candidate


def test_bibtex_macros_crossref_and_author_lists():
    rows = _bib_candidates(1, {"refs.bib": r'''
@string{j = "Journal of " # "Examples"}
@proceedings{parent, title={Conference}, year=2019, journal=j, doi={10.1234/parent}}
@inproceedings{child, crossref={parent}, title={Child}, author={J. Smith and {Research and Development}}}
'''}, [])
    rows = {row.key: row.fields for row in rows}
    assert rows["child"]["year"] == 2019
    assert rows["child"]["journal"] == "Journal of Examples"
    assert rows["child"]["authors"] == ["J. Smith", "{Research and Development}"]
    assert rows["child"]["doi"] is None and len(rows) == 2



@pytest.mark.parametrize(("body", "title"), [
    (r"Fry, P. J., {\it Introduction to Analysis}, 2nd ed., Example Press, 2020.",
     "Introduction to Analysis"),
    (r"A. Doe, and B. Smith, \emph{A Study of Light}, J. Opt. {\bf 12}, 1 (2020).",
     "A Study of Light"),
    (r"Ya. A. Doe, B. Smith, and C. West, Optical analysis, J. Opt. {\bf 12}, 1 (2020).",
     "Optical analysis"),
    (r"A. Doe, B. Smith, and Andr{\'e}s West. Analysis of light. Preprint, {\em arXiv:2401.12345}, 2024.",
     "Analysis of light"),
    (r"A. Doe. Light and matter vs. fields. II. Optical effects. \emph{J. Opt.}, 2020.",
     "Light and matter vs. fields. II. Optical effects"),
    (r"Z.\ Doe, {\sl A study of $\tilde{A}$, light, and matter\/}. In preparation.",
     r"A study of $\tilde{A}$, light, and matter"),
    (r'A. M\"{u}ller and B. G\"{o}tz. Rates in $3.2$, and beyond. J. Opt. 2020.',
     "Rates in $3.2$, and beyond"),
    ("A. Doe, J. Opt. {\\bf 12}, 1 (2020).\n% Title only in a comment",
     None),
    (r"A.\ Doe, J.\ Opt.: Condens.\ Matter {\bf 12\/}, 43--48 (2020).",
     None),
    (r"As a concrete example, consider the function $f(x)=x^2$. It vanishes at $0$.",
     None),
])
def test_bibitem_title_boundaries(body, title):
    candidate = _bibitem_candidate(1, r"\bibitem{item} " + body)
    assert candidate.fields["title"] == title

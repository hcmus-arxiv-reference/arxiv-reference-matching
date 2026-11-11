#include "hierarchy_parser.hpp"

#include <algorithm>
#include <fstream>
#include <functional>
#include <iostream>
#include <regex>
#include <set>
#include <stdexcept>
#include <utility>

using arxiv::parse::Element;
using arxiv::parse::HierarchyParser;
using arxiv::parse::ParseResult;

namespace {

void check(bool condition, const std::string& message) {
    if (!condition) throw std::runtime_error(message);
}

ParseResult parse(const std::string& text, int version = 1) {
    return HierarchyParser("2508.02872", version, MAPPING_PATH).parse(text);
}

std::vector<Element> of_kind(const ParseResult& result, const std::string& kind) {
    std::vector<Element> out;
    for (const auto& element : result.elements) if (element.kind == kind) out.push_back(element);
    return out;
}

const Element& find(const ParseResult& result, const std::string& kind, const std::string& content) {
    for (const auto& element : result.elements)
        if (element.kind == kind && element.content == content) return element;
    throw std::runtime_error("Missing " + kind + ": " + content);
}

std::string parent_of(const ParseResult& result, const std::string& id) {
    for (const auto& edge : result.hierarchy) if (edge.element_id == id) return edge.parent_id;
    throw std::runtime_error("Missing parent for " + id);
}

void valid_edges(const ParseResult& result) {
    std::set<std::string> ids;
    for (const auto& element : result.elements) {
        check(ids.insert(element.element_id).second, "Duplicate elements row");
        check(element.arxiv_id == "2508.02872", "Wrong arxiv_id");
        check(std::regex_match(element.element_id,
              std::regex("2508-02872#[a-z]+-[0-9a-f]{16}")), "Wrong ID format");
    }
    std::set<std::pair<std::string, std::string>> edges;
    for (const auto& edge : result.hierarchy) {
        check(ids.count(edge.element_id) && ids.count(edge.parent_id), "Broken foreign key");
        check(edges.emplace(edge.element_id, edge.parent_id).second, "Duplicate hierarchy row");
    }
    for (const auto& root : of_kind(result, "document"))
        for (const auto& edge : result.hierarchy)
            check(edge.element_id != root.element_id, "Root must not have a parent edge");
}

void basic_tree() {
    const auto result = parse(R"(\documentclass{article}
\newcommand{\fake}{\section{Do not parse}}
\begin{document}\section{Intro}First. Second.
\subsection{Method}Third.\end{document}\section{After end}Hidden.)");
    check(result.complete(), "Basic tree should be complete");
    check(result.elements.size() == 6, "Wrong basic node count");
    const auto& section = find(result, "section", "Intro");
    check(parent_of(result, find(result, "subsection", "Method").element_id) == section.element_id, "Subsection parent");
    check(parent_of(result, find(result, "sentence", "First.").element_id) == section.element_id, "Sentence parent");
    valid_edges(result);
}

void missing_levels_and_stars() {
    const auto result = parse(R"(\subsection*{Intro}A.\paragraph{Detail}B.\section*{Next}C.)");
    check(result.complete(), "Skipped levels");
    const auto root = of_kind(result, "document").front().element_id;
    const auto sub = find(result, "subsection", "Intro").element_id;
    check(parent_of(result, sub) == root, "No synthetic missing heading");
    check(parent_of(result, find(result, "paragraph", "Detail").element_id) == sub, "Paragraph relative level");
    check(parent_of(result, find(result, "section", "Next").element_id) == root, "Heading stack pop");
    valid_edges(result);
}

void references_acknowledgements_and_appendix() {
    const auto result = parse(R"(\section{Body}Keep.
\section*{References}Hidden.\subsection{Still hidden}Secret.
\section*{Acknowledgements}Thanks.
\appendix\section*{Appendix A}Details.
\begin{thebibliography}{9}\bibitem{x}Excluded.\end{thebibliography}
\bibliography{refs}\printbibliography)");
    check(result.complete(), "References exclusion");
    check(of_kind(result, "section").size() == 3, "References heading leaked");
    check(of_kind(result, "sentence").size() == 3, "References text leaked");
    find(result, "sentence", "Details.");
    valid_edges(result);
}

void sentence_protection() {
    const auto result = parse(R"(Use i.e. examples and et al. in Fig. 2 with 3.14 at https://example.org/a.b. Next \textbf{not. split} and $a.b$.)");
    check(result.complete(), "Sentence protection");
    const auto sentences = of_kind(result, "sentence");
    check(sentences.size() == 2, "Split inside protected prose");
    check(sentences[0].content.find("https://example.org/a.b.") != std::string::npos, "URL changed");
    check(sentences[1].content == R"(Next \textbf{not. split} and $a.b$.)", "Command/math content changed");
}

void figure_reference_variants() {
    for (const auto& input : {std::string("See Fig. 10. Next."), std::string("See Figs.~2 and 3. Next."),
                             std::string("See Fig.\xC2\xA0" "2. Next."), std::string(R"(See Fig.~\ref{x}. Next.)")}) {
        const auto result = parse(input);
        check(result.complete(), "Figure reference diagnostic");
        check(of_kind(result, "sentence").size() == 2, "Figure reference split");
    }
}

void comments_and_literals() {
    const auto result = parse(R"(% \section{Fake}
\section{Real}Escaped \% remains. % \section{Fake 2}
Literal \verb|\section{Fake 3}.| stays.)");
    check(result.complete(), "Comments and inline verbatim");
    check(of_kind(result, "section").size() == 1, "Fake heading parsed");
    check(of_kind(result, "sentence").size() == 2, "Inline verbatim split");
}

void nested_lists() {
    const auto result = parse(R"(\section{Items}\begin{itemize}
\item First.\begin{enumerate}\item Nested.\end{enumerate}
\item Second.\end{itemize})");
    check(result.complete(), "Nested list");
    const auto lists = of_kind(result, "itemize");
    check(lists.size() == 2 && of_kind(result, "item").size() == 3, "List node counts");
    check(parent_of(result, lists[1].element_id) == parent_of(result, find(result, "sentence", "First.").element_id), "Nested list belongs to item");
    valid_edges(result);
}

void description_labels() {
    const auto result = parse(R"(\begin{description}\item[Term] Definition.\end{description})");
    check(result.complete(), "Description mapping");
    find(result, "sentence", "Term Definition.");
    check(of_kind(result, "item").size() == 1, "Description item");
}

void math_and_figure_leaves() {
    const auto result = parse(R"(Before \(x.y\). $$a.b$$
\begin{align}a&=b\\c&=d\end{align}
\begin{figure*}[htpb]\centering\caption{A. B.}\end{figure*}
\begin{table}\begin{tabular}{c}Cell.\end{tabular}\end{table}After.)");
    check(result.complete(), "Math/figure parse");
    check(of_kind(result, "formula").size() == 2, "Block formula count");
    check(of_kind(result, "figure").size() == 2, "Tables map to figure");
    check(of_kind(result, "sentence").size() == 2, "Split inside atomic leaf");
    find(result, "sentence", "Before $x.y$.");
    find(result, "formula", R"(\begin{align}a&=b\\c&=d\end{align})");
    valid_edges(result);
}

void abstract_under_document() {
    const auto result = parse(R"(\documentclass{article}\begin{document}
\begin{abstract}Summary.\end{abstract}\section{Intro}Body.\end{document})");
    check(result.complete(), "Abstract mapping");
    const auto root = of_kind(result, "document").front().element_id;
    const auto abstract = find(result, "section", "Abstract").element_id;
    check(parent_of(result, abstract) == root, "Abstract must be under document");
    check(parent_of(result, find(result, "sentence", "Summary.").element_id) == abstract, "Abstract prose parent");
    check(parent_of(result, find(result, "section", "Intro").element_id) == root, "Abstract scope leaked");
}

void deduplication_and_order() {
    const auto result = parse(R"(\section{A}Same. Same.\section{B}Same.)");
    check(result.complete(), "Dedup parse");
    check(of_kind(result, "sentence").size() == 1, "Repeated sentence must share ID");
    const auto sentence = find(result, "sentence", "Same.").element_id;
    const auto heading = find(result, "section", "A").element_id;
    int edges = 0;
    for (const auto& edge : result.hierarchy) if (edge.element_id == sentence) ++edges;
    check(edges == 2, "Same element may have two parents, but no duplicate edge");
    check(result.ordered_children.at(heading) == std::vector<std::string>({sentence, sentence}), "Intermediate order must retain repeated occurrence");
    valid_edges(result);
}

void stable_ids_across_versions() {
    const auto v1 = parse(R"(\section{Same title}Same. Old.)", 1);
    const auto v2 = parse(R"(\section{Same title}Same. New.)", 2);
    check(find(v1, "sentence", "Same.").element_id == find(v2, "sentence", "Same.").element_id, "Leaf ID changed across versions");
    check(find(v1, "sentence", "Same.").element_id == "2508-02872#sentence-5906e4aa68c69acf", "SHA-256 serialization changed");
    check(find(v1, "section", "Same title").element_id != find(v2, "section", "Same title").element_id, "Heading ID must include subtree");
    for (const auto& edge : v2.hierarchy) check(edge.version == 2, "Wrong version");
    const auto rerun = parse(R"(\section{Same title}Same. Old.)", 1);
    check(of_kind(v1, "document")[0].element_id == of_kind(rerun, "document")[0].element_id, "Non-deterministic IDs");
    const auto swapped = parse(R"(\section{Same title}Old. Same.)", 1);
    check(of_kind(v1, "document")[0].element_id != of_kind(swapped, "document")[0].element_id, "Hash ignored child order");
}

void unknown_sources_preserved_in_diagnostics() {
    const auto result = parse(R"(Before.\begin{verbatim}\section{Fake}%literal\end{verbatim}
\unknown{Keep. this} After.)");
    check(!result.complete(), "Unknown source must be reported");
    check(of_kind(result, "section").empty(), "Verbatim heading parsed");
    check(result.diagnostics.front().source.find("%literal") != std::string::npos, "Opaque source was discarded");
    bool preserved = false;
    for (const auto& e : of_kind(result, "sentence")) if (e.content.find("\\unknown{Keep. this}") != std::string::npos) preserved = true;
    check(preserved, "Unknown command was discarded");
}

void malformed_sources_are_not_successful() {
    for (const auto* text : {R"(\section{Broken)", R"(\begin{itemize}\item A.)",
                             R"(\begin{figure}x\end{table})", R"(\documentclass{article}No body.)",
                             R"(\begin{document}Missing end.)", R"($unclosed)", R"(\item Outside.)"}) {
        const auto result = parse(text);
        check(!result.complete(), "Malformed input reported success");
        valid_edges(result);
    }
}

void literal_conditionals() {
    const auto result = parse(R"(\iftrue\section{Kept}Visible.\else\section{Hidden}Secret.\fi
\iffalse\section{Hidden 2}Secret.\fi)");
    check(result.complete(), "Literal conditions");
    check(of_kind(result, "section").size() == 1, "Inactive heading leaked");
    check(of_kind(result, "sentence").size() == 1, "Inactive prose leaked");
}

void empty_input_and_reset() {
    const HierarchyParser parser("2508.02872", 1, MAPPING_PATH);
    check(parser.parse(" \n\t").elements.empty(), "Empty Version should stay empty");
    const auto first = parser.parse("First.");
    const auto second = parser.parse("Second.");
    check(of_kind(first, "sentence").size() == 1 && of_kind(second, "sentence").size() == 1, "Parser state leaked");
    find(second, "sentence", "Second.");
}

void mapping_is_loaded() {
    std::ifstream input(MAPPING_PATH);
    nlohmann::json mapping;
    input >> mapping;
    mapping["commands"]["\\customheading"] = {{"kind", "section"}, {"level", 2}, {"content", "title"}};
    const std::filesystem::path path = "custom_mapping_test.json";
    { std::ofstream output(path); output << mapping; }
    const auto result = HierarchyParser("2508.02872", 1, path).parse(R"(\customheading{Custom}Body.)");
    std::filesystem::remove(path);
    check(result.complete(), "Custom mapping not applied");
    find(result, "section", "Custom");
}

}  // namespace

int main() {
    const std::vector<std::pair<std::string, std::function<void()>>> tests = {
        {"basic_tree", basic_tree}, {"missing_levels_and_stars", missing_levels_and_stars},
        {"references_acknowledgements_and_appendix", references_acknowledgements_and_appendix},
        {"sentence_protection", sentence_protection}, {"figure_reference_variants", figure_reference_variants},
        {"comments_and_literals", comments_and_literals}, {"nested_lists", nested_lists},
        {"description_labels", description_labels}, {"math_and_figure_leaves", math_and_figure_leaves},
        {"abstract_under_document", abstract_under_document}, {"deduplication_and_order", deduplication_and_order},
        {"stable_ids_across_versions", stable_ids_across_versions},
        {"unknown_sources_preserved_in_diagnostics", unknown_sources_preserved_in_diagnostics},
        {"malformed_sources_are_not_successful", malformed_sources_are_not_successful},
        {"literal_conditionals", literal_conditionals}, {"empty_input_and_reset", empty_input_and_reset},
        {"mapping_is_loaded", mapping_is_loaded},
    };
    int failures = 0;
    for (const auto& [name, test] : tests) {
        try { test(); std::cout << "PASS " << name << '\n'; }
        catch (const std::exception& error) { ++failures; std::cerr << "FAIL " << name << ": " << error.what() << '\n'; }
    }
    std::cout << tests.size() - failures << '/' << tests.size() << " test groups passed\n";
    return failures == 0 ? 0 : 1;
}

#pragma once

#include <filesystem>
#include <map>
#include <string>
#include <vector>

#include <nlohmann/json.hpp>

namespace arxiv::parse {

struct Element {
    std::string element_id;
    std::string arxiv_id;
    std::string kind;
    std::string content;
};

struct Hierarchy {
    std::string arxiv_id;
    int version;
    std::string element_id;
    std::string parent_id;
};

struct Diagnostic {
    std::string code;
    std::size_t offset;
    std::string message;
    std::string source;
};

struct ParseResult {
    std::vector<Element> elements;
    std::vector<Hierarchy> hierarchy;
    std::vector<Diagnostic> diagnostics;
    // Intermediate reading order (including repeats), not a new dataset table.
    std::map<std::string, std::vector<std::string>> ordered_children;

    bool complete() const { return diagnostics.empty(); }
};

class HierarchyParser {
public:
    // arxiv_id has no version suffix; mapping_path points to Hierarchy/mapping.json.
    HierarchyParser(std::string arxiv_id, int version,
                    const std::filesystem::path& mapping_path);

    // Accepts a merged document or a body fragment. Expands bounded source-defined
    // macros/newtheorem and literal/newif booleans; does not execute arbitrary TeX/packages.
    // Executes command/environment actions and normalization declared in mapping.
    // Unsupported constructs remain diagnostics; check complete() before dataset use.
    // Citation keys are preserved; BibTeX key rewriting is a separate stage.
    // IDs hash compact UTF-8 JSON [kind, content] for leaves, or
    // [kind, content, ordered_child_ids] for structural nodes (SHA-256, 16 hex).
    ParseResult parse(const std::string& latex) const;

private:
    std::string arxiv_id_;
    int version_;
    nlohmann::json mapping_;
};

}  // namespace arxiv::parse

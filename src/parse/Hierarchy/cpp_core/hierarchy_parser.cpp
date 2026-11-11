#include "hierarchy_parser.hpp"

#include <algorithm>
#include <cctype>
#include <fstream>
#include <functional>
#include <iomanip>
#include <optional>
#include <regex>
#include <set>
#include <sstream>
#include <stdexcept>
#include <utility>

#include <openssl/evp.h>

namespace arxiv::parse {
namespace {

using Json = nlohmann::json;

bool space(char c) { return std::isspace(static_cast<unsigned char>(c)) != 0; }
bool letter(char c) { return std::isalpha(static_cast<unsigned char>(c)) != 0; }
bool digit(char c) { return std::isdigit(static_cast<unsigned char>(c)) != 0; }

std::string lower(std::string text) {
    for (char& c : text) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    return text;
}

std::string compact(const std::string& text) {
    std::string out;
    bool gap = false;
    for (char c : text) {
        if (space(c)) {
            gap = !out.empty();
        } else {
            if (gap) out += ' ';
            out += c;
            gap = false;
        }
    }
    return out;
}

struct Command {
    std::string name;
    std::size_t end;
};

Command command_at(const std::string& text, std::size_t start) {
    std::size_t end = start + 1;
    if (end < text.size() && (letter(text[end]) || text[end] == '@')) {
        while (end < text.size() && (letter(text[end]) || text[end] == '@')) ++end;
        if (end < text.size() && text[end] == '*') ++end;
    } else if (end < text.size()) {
        ++end;
    }
    return {text.substr(start, end - start), end};
}

std::size_t skip_space(const std::string& text, std::size_t pos) {
    while (pos < text.size()) {
        if (space(text[pos])) {
            ++pos;
        } else if (text[pos] == '%') {
            const auto end = text.find('\n', pos);
            pos = end == std::string::npos ? text.size() : end + 1;
        } else {
            break;
        }
    }
    return pos;
}

struct Group {
    std::string text;
    std::size_t end;
};

Group group_at(const std::string& text, std::size_t pos, char opening = '{') {
    pos = skip_space(text, pos);
    if (pos == text.size() || text[pos] != opening)
        throw std::runtime_error("Expected a grouped argument");
    const char closing = opening == '{' ? '}' : ']';
    int depth = 1;
    std::string body;
    for (++pos; pos < text.size();) {
        if (text[pos] == '\\') {
            const auto cmd = command_at(text, pos);
            body += text.substr(pos, cmd.end - pos);
            pos = cmd.end;
        } else if (text[pos] == '%') {
            const auto end = text.find('\n', pos);
            pos = end == std::string::npos ? text.size() : end + 1;
        } else {
            const char c = text[pos++];
            if (c == opening) ++depth;
            if (c == closing) {
                --depth;
                if (depth == 0) return {body, pos};
            }
            body += c;
        }
    }
    throw std::runtime_error("Unclosed grouped argument");
}

std::size_t arguments_end(const std::string& text, std::size_t pos) {
    while (true) {
        const auto next = skip_space(text, pos);
        if (next == text.size() || (text[next] != '{' && text[next] != '[')) return pos;
        pos = group_at(text, next, text[next]).end;
    }
}

std::size_t verb_end(const std::string& text, std::size_t pos) {
    if (pos == text.size() || space(text[pos])) throw std::runtime_error("Missing verb delimiter");
    const auto end = text.find(text[pos], pos + 1);
    if (end == std::string::npos || text.substr(pos, end - pos).find('\n') != std::string::npos)
        throw std::runtime_error("Unclosed inline verbatim");
    return end + 1;
}

const std::set<std::string> definitions = {
    "\\newcommand", "\\renewcommand", "\\providecommand", "\\DeclareRobustCommand",
    "\\newcommand*", "\\renewcommand*", "\\providecommand*", "\\DeclareRobustCommand*",
    "\\newenvironment", "\\renewenvironment", "\\def", "\\gdef", "\\edef", "\\xdef"
};

std::size_t definition_end(const std::string& text, const Command& cmd) {
    auto pos = skip_space(text, cmd.end);
    const bool primitive = cmd.name == "\\def" || cmd.name == "\\gdef" ||
                           cmd.name == "\\edef" || cmd.name == "\\xdef";
    if (pos < text.size() && text[pos] == '\\') pos = command_at(text, pos).end;
    else pos = group_at(text, pos).end;
    if (primitive) {
        while (pos < text.size() && text[pos] != '{') ++pos;
    } else {
        pos = skip_space(text, pos);
        while (pos < text.size() && text[pos] == '[')
            pos = skip_space(text, group_at(text, pos, '[').end);
    }
    pos = group_at(text, pos).end;
    if (cmd.name.find("environment") != std::string::npos) pos = group_at(text, pos).end;
    return pos;
}

struct Environment {
    std::string body;
    std::size_t end;
};

Environment environment_at(const std::string& text, std::size_t body_start,
                           const std::string& name) {
    // Verbatim bodies must not be interpreted as LaTeX commands.
    const std::set<std::string> literal = {"verbatim", "verbatim*", "Verbatim", "lstlisting", "minted", "comment"};
    if (literal.count(name)) {
        const std::string closing = "\\end{" + name + "}";
        const auto end = text.find(closing, body_start);
        if (end == std::string::npos) throw std::runtime_error("Unclosed environment: " + name);
        return {text.substr(body_start, end - body_start), end + closing.size()};
    }
    std::vector<std::string> stack{name};
    for (auto pos = body_start; pos < text.size();) {
        if (text[pos] == '%') {
            const auto end = text.find('\n', pos);
            pos = end == std::string::npos ? text.size() : end + 1;
        } else if (text[pos] != '\\') {
            ++pos;
        } else {
            const auto start = pos;
            const auto cmd = command_at(text, pos);
            pos = cmd.end;
            if (cmd.name == "\\verb" || cmd.name == "\\verb*") {
                pos = verb_end(text, pos);
            } else if (definitions.count(cmd.name)) {
                pos = definition_end(text, cmd);
            } else if (cmd.name == "\\begin" || cmd.name == "\\end") {
                const auto arg = group_at(text, pos);
                pos = arg.end;
                if (cmd.name == "\\begin") {
                    if (literal.count(arg.text)) pos = environment_at(text, pos, arg.text).end;
                    else stack.push_back(arg.text);
                } else {
                    if (stack.back() != arg.text) throw std::runtime_error("Mismatched environment: " + arg.text);
                    stack.pop_back();
                    if (stack.empty()) return {text.substr(body_start, start - body_start), pos};
                }
            }
        }
    }
    throw std::runtime_error("Unclosed environment: " + name);
}

std::string clean_comments(const std::string& text) {
    std::string out;
    for (std::size_t pos = 0; pos < text.size();) {
        if (text[pos] == '%') {
            const auto end = text.find('\n', pos);
            pos = end == std::string::npos ? text.size() : end + 1;
        } else if (text[pos] == '\\') {
            const auto start = pos;
            const auto cmd = command_at(text, pos);
            pos = cmd.end;
            if (cmd.name == "\\verb" || cmd.name == "\\verb*") pos = verb_end(text, pos);
            if (cmd.name != "\\centering" && cmd.name != "\\midrule") out += text.substr(start, pos - start);
        } else {
            out += text[pos++];
        }
    }
    return compact(out);
}

std::string digest(const std::string& payload) {
    unsigned char bytes[EVP_MAX_MD_SIZE];
    unsigned int length = 0;
    if (EVP_Digest(payload.data(), payload.size(), bytes, &length, EVP_sha256(), nullptr) != 1)
        throw std::runtime_error("SHA-256 failed");
    std::ostringstream out;
    for (unsigned int i = 0; i < length; ++i)
        out << std::hex << std::setw(2) << std::setfill('0') << static_cast<int>(bytes[i]);
    return out.str();
}

struct Node {
    std::string kind;
    std::string content;
    int level;
    std::vector<std::size_t> children;
    std::string id;
};

class Engine {
public:
    Engine(const Json& mapping, const std::string& latex, const std::string& arxiv_id, int version)
        : mapping(mapping), text(latex), arxiv_id(arxiv_id), version(version) {}

    ParseResult run() {
        if (compact(text).empty()) return {};
        nodes.push_back({"document", "", 0, {}, ""});
        headings.push_back(0);
        std::size_t pos = 0;
        try {
            pos = body_start();
            parse_body(pos);
            if (!lists.empty()) throw std::runtime_error("Unclosed list environment");
            if (abstract_headings) throw std::runtime_error("Unclosed abstract environment");
            if (!conditions.empty()) throw std::runtime_error("Unclosed conditional");
            flush();
        } catch (const std::runtime_error& error) {
            issue("invalid_syntax", pos, error.what(), "");
        }
        assign_ids(0, 0);
        std::set<std::string> elements_seen;
        std::set<std::pair<std::string, std::string>> edges_seen;
        export_nodes(0, elements_seen, edges_seen);
        return std::move(result);
    }

private:
    const Json& mapping;
    const std::string& text;
    const std::string& arxiv_id;
    int version;
    ParseResult result;
    std::vector<Node> nodes;
    std::vector<std::size_t> headings;
    struct ListFrame { std::string name; std::size_t node; std::optional<std::size_t> item; };
    std::vector<ListFrame> lists;
    std::optional<std::vector<std::size_t>> abstract_headings;
    std::vector<std::optional<bool>> conditions;
    std::optional<int> excluded_level;
    bool wrapped = false;
    bool ended = false;
    std::string prose;
    std::vector<bool> protected_chars;

    void issue(const std::string& code, std::size_t offset, const std::string& message,
               const std::string& source) {
        result.diagnostics.push_back({code, offset, message, source});
    }

    std::size_t parent() const {
        if (!lists.empty()) return lists.back().item.value_or(lists.back().node);
        return headings.back();
    }

    std::size_t add(const std::string& kind, const std::string& content, int level = 0) {
        const auto index = nodes.size();
        nodes[parent()].children.push_back(index);
        nodes.push_back({kind, content, level, {}, ""});
        return index;
    }

    void append(const std::string& value, bool protect = false) {
        if (excluded_level) return;
        prose += value;
        protected_chars.insert(protected_chars.end(), value.size(), protect);
    }

    bool active() const {
        return std::all_of(conditions.begin(), conditions.end(), [](auto value) {
            return value.has_value() && *value;
        });
    }

    bool contains(const Json& entries, const std::string& value) const {
        return std::any_of(entries.begin(), entries.end(), [&](const auto& entry) {
            return entry.template get<std::string>() == value;
        });
    }

    void mark(std::size_t start, std::size_t end) {
        for (auto i = start; i < end; ++i) protected_chars[i] = true;
    }

    void flush() {
        if (prose.empty()) return;
        const auto folded = lower(prose);
        for (const auto& value : mapping.at("sentence").at("abbreviations")) {
            const auto abbreviation = lower(value.get<std::string>());
            for (std::size_t pos = 0; (pos = folded.find(abbreviation, pos)) != std::string::npos; ++pos) {
                if (pos == 0 || !letter(prose[pos - 1])) mark(pos, pos + abbreviation.size());
            }
        }
        for (const auto& rule : mapping.at("sentence").at("protected_patterns")) {
            auto pattern = rule.at("pattern").get<std::string>();
            auto flags = std::regex::ECMAScript;
            if (pattern.rfind("(?i)", 0) == 0) {
                pattern.erase(0, 4);
                flags |= std::regex::icase;
            }
            // std::regex is byte-based; explicitly include UTF-8 nonbreaking spaces.
            const auto whitespace = pattern.find("[\\s~]*");
            if (whitespace != std::string::npos)
                pattern.replace(whitespace, 6, "(?:\\s|~|\\xC2\\xA0)*");
            const std::regex expression(pattern, flags);
            for (auto it = std::sregex_iterator(prose.begin(), prose.end(), expression);
                 it != std::sregex_iterator(); ++it)
                mark(static_cast<std::size_t>(it->position()), static_cast<std::size_t>(it->position() + it->length()));
        }
        const std::regex url(R"((https?://|www\.)[^\s<>{}]+)", std::regex::icase);
        for (auto it = std::sregex_iterator(prose.begin(), prose.end(), url); it != std::sregex_iterator(); ++it) {
            const auto start = static_cast<std::size_t>(it->position());
            auto end = start + static_cast<std::size_t>(it->length());
            while (end > start && std::string(".,!?;:)]").find(prose[end - 1]) != std::string::npos) --end;
            mark(start, end);
        }
        std::size_t start = 0;
        for (std::size_t pos = 0; pos < prose.size(); ++pos) {
            if (prose[pos] != '.' || protected_chars[pos]) continue;
            if (pos + 1 < prose.size() && prose[pos + 1] == '.') continue;
            if (pos > 0 && pos + 1 < prose.size() && digit(prose[pos - 1]) && digit(prose[pos + 1])) continue;
            const auto sentence = compact(prose.substr(start, pos + 1 - start));
            if (!sentence.empty()) add("sentence", sentence);
            start = pos + 1;
        }
        const auto tail = compact(prose.substr(start));
        if (!tail.empty()) add("sentence", tail);
        prose.clear();
        protected_chars.clear();
    }

    std::size_t body_start() {
        bool declared = false;
        for (std::size_t pos = 0; pos < text.size();) {
            if (text[pos] == '%') {
                const auto end = text.find('\n', pos);
                pos = end == std::string::npos ? text.size() : end + 1;
            } else if (text[pos] != '\\') {
                ++pos;
            } else {
                const auto cmd = command_at(text, pos);
                pos = cmd.end;
                if (definitions.count(cmd.name)) pos = definition_end(text, cmd);
                else if (cmd.name == "\\verb" || cmd.name == "\\verb*") pos = verb_end(text, pos);
                else if (cmd.name == "\\documentclass") declared = true;
                else if (cmd.name == "\\begin") {
                    const auto group = group_at(text, pos);
                    pos = group.end;
                    if (group.text == "document") { wrapped = true; return pos; }
                    pos = environment_at(text, pos, group.text).end;
                }
            }
        }
        if (declared) throw std::runtime_error("Missing begin{document}");
        return 0;
    }

    void heading(const Json& rule, const std::string& title, std::size_t offset) {
        flush();
        const int level = rule.at("level");
        if (excluded_level && level > *excluded_level) return;
        excluded_level.reset();
        const auto title_key = lower(compact(title));
        for (const auto& excluded : mapping.at("exclusions").at("heading_titles")) {
            if (title_key == lower(excluded.get<std::string>())) { excluded_level = level; return; }
        }
        if (!lists.empty()) {
            issue("heading_inside_list", offset, "Heading inside an item needs explicit hierarchy rules", title);
            return;
        }
        while (headings.size() > 1 && nodes[headings.back()].level >= level) headings.pop_back();
        if (headings.size() >= 256) throw std::runtime_error("Hierarchy depth exceeds 256");
        headings.push_back(add(rule.at("kind"), clean_comments(title), level));
    }

    void parse_body(std::size_t& pos) {
        while (pos < text.size()) {
            if (text[pos] == '%') {
                const auto end = text.find('\n', pos);
                pos = end == std::string::npos ? text.size() : end + 1;
                continue;
            }
            if (text[pos] == '$' && active()) {
                const bool block = pos + 1 < text.size() && text[pos + 1] == '$';
                const std::string delimiter = block ? "$$" : "$";
                const auto start = pos;
                auto end = pos + delimiter.size();
                while (end < text.size()) {
                    if (text[end] == '\\') end = command_at(text, end).end;
                    else if (text.compare(end, delimiter.size(), delimiter) == 0) break;
                    else ++end;
                }
                if (end == text.size()) throw std::runtime_error("Unclosed math delimiter");
                const auto body = text.substr(start + delimiter.size(), end - start - delimiter.size());
                pos = end + delimiter.size();
                if (block) {
                    flush();
                    if (!excluded_level) add("formula", "\\begin{equation}" + clean_comments(body) + "\\end{equation}");
                } else append("$" + body + "$", true);
                continue;
            }
            if (text[pos] != '\\') {
                if (active()) append(text.substr(pos, 1));
                ++pos;
                continue;
            }
            const auto start = pos;
            const auto cmd = command_at(text, pos);
            pos = cmd.end;
            if (cmd.name == "\\iftrue" || cmd.name == "\\iffalse") {
                conditions.push_back(cmd.name == "\\iftrue");
                continue;
            }
            if (cmd.name == "\\else") {
                if (conditions.empty()) throw std::runtime_error("Unmatched else");
                if (conditions.back()) conditions.back() = !*conditions.back();
                continue;
            }
            if (cmd.name == "\\fi") {
                if (conditions.empty()) throw std::runtime_error("Unmatched fi");
                conditions.pop_back();
                continue;
            }
            if (!active()) {
                if (cmd.name.rfind("\\if", 0) == 0) conditions.push_back(std::nullopt);
                continue;
            }
            if (definitions.count(cmd.name)) {
                pos = definition_end(text, cmd);
                if (!excluded_level) issue("unexpanded_definition", start, "Macro definitions are not executed", text.substr(start, pos - start));
                continue;
            }
            if (cmd.name == "\\verb" || cmd.name == "\\verb*") {
                pos = verb_end(text, pos);
                append(text.substr(start, pos - start), true);
                continue;
            }
            if (cmd.name == "\\[" || cmd.name == "\\(") {
                const bool block = cmd.name == "\\[";
                const std::string closing = block ? "\\]" : "\\)";
                auto end = pos;
                while (end < text.size()) {
                    if (text[end] != '\\') { ++end; continue; }
                    const auto token = command_at(text, end);
                    if (token.name == closing) break;
                    end = token.end;
                }
                if (end == text.size()) throw std::runtime_error("Unclosed math delimiter");
                const auto body = text.substr(pos, end - pos);
                pos = end + closing.size();
                if (block) {
                    flush();
                    if (!excluded_level) add("formula", "\\begin{equation}" + clean_comments(body) + "\\end{equation}");
                } else append("$" + body + "$", true);
                continue;
            }
            if (cmd.name == "\\begin") {
                const auto group = group_at(text, pos);
                pos = group.end;
                const auto name = group.text;
                if (name == "abstract" && !excluded_level) {
                    flush();
                    if (abstract_headings || !lists.empty()) throw std::runtime_error("Invalid abstract nesting");
                    abstract_headings = headings;
                    headings = {0};
                    const auto& rule = mapping.at("environments").at("abstract");
                    headings.push_back(add(rule.at("kind"), "Abstract", rule.at("level")));
                    continue;
                }
                const auto& environments = mapping.at("environments");
                if (environments.contains(name) && environments.at(name).at("kind") == "itemize" && !excluded_level) {
                    flush();
                    if (lists.size() >= 128) throw std::runtime_error("List depth exceeds 128");
                    lists.push_back({name, add("itemize", ""), std::nullopt});
                    continue;
                }
                const auto environment = environment_at(text, pos, name);
                pos = environment.end;
                if (excluded_level || contains(mapping.at("exclusions").at("environments"), name) || name == "comment") continue;
                flush();
                const auto& rules = mapping.at("environments");
                if (!rules.contains(name)) {
                    issue("unhandled_environment", start, "Environment has no settled mapping: " + name,
                          text.substr(start, pos - start));
                } else if (rules.at(name).at("kind") == "formula") {
                    // Preserve multi-line environments for the later normalization stage.
                    add("formula", clean_comments(text.substr(start, pos - start)));
                } else if (rules.at(name).at("kind") == "figure") {
                    add("figure", clean_comments(text.substr(start, pos - start)));
                } else {
                    issue("unhandled_environment", start, "Nested document or unsupported container", text.substr(start, pos - start));
                }
                continue;
            }
            if (cmd.name == "\\end") {
                const auto group = group_at(text, pos);
                pos = group.end;
                if (group.text == "document" && wrapped) {
                    if (!lists.empty() || abstract_headings) throw std::runtime_error("Document ended inside an open container");
                    ended = true;
                    break;
                }
                if (group.text == "abstract" && abstract_headings && !excluded_level) {
                    flush();
                    headings = *abstract_headings;
                    abstract_headings.reset();
                    continue;
                }
                if (lists.empty() || group.text != lists.back().name) throw std::runtime_error("Unexpected end{" + group.text + "}");
                flush();
                lists.pop_back();
                continue;
            }
            const auto& commands = mapping.at("commands");
            if (commands.contains(cmd.name) && commands.at(cmd.name).contains("level")) {
                auto next = skip_space(text, pos);
                if (next < text.size() && text[next] == '[') pos = group_at(text, next, '[').end;
                const auto title = group_at(text, pos);
                pos = title.end;
                heading(commands.at(cmd.name), title.text, start);
            } else if (cmd.name == "\\item" && !excluded_level) {
                flush();
                if (lists.empty()) throw std::runtime_error("Item outside itemize");
                auto next = skip_space(text, pos);
                if (next < text.size() && text[next] == '[') {
                    const auto label = group_at(text, next, '[');
                    pos = label.end;
                    // The label is visible prose; retain it in the item's first sentence.
                    lists.back().item.reset();
                    const auto index = nodes.size();
                    nodes[lists.back().node].children.push_back(index);
                    nodes.push_back({"item", "", 0, {}, ""});
                    lists.back().item = index;
                    append(label.text + " ", true);
                    continue;
                }
                const auto index = nodes.size();
                nodes[lists.back().node].children.push_back(index);
                nodes.push_back({"item", "", 0, {}, ""});
                lists.back().item = index;
            } else if (cmd.name == "\\appendix") {
                flush();
                excluded_level.reset();
            } else if (contains(mapping.at("exclusions").at("commands"), cmd.name)) {
                pos = arguments_end(text, pos);
            } else if (cmd.name == "\\centering" || cmd.name == "\\midrule") {
                // Formatting does not contribute an Element.
            } else if (cmd.name == "\\endinput") {
                break;
            } else {
                pos = arguments_end(text, pos);
                if (!excluded_level) {
                    append(text.substr(start, pos - start), true);
                    const std::set<std::string> inline_commands = {
                        "\\textbf", "\\textit", "\\emph", "\\textrm", "\\texttt", "\\textsf",
                        "\\cite", "\\citep", "\\citet", "\\cite*", "\\ref", "\\eqref", "\\autoref",
                        "\\cref", "\\Cref", "\\url", "\\href", "\\label", "\\%", "\\&", "\\_", "\\$", "\\#", "\\{", "\\}"
                    };
                    if (!inline_commands.count(cmd.name))
                        issue("unhandled_command", start, "Command preserved without macro expansion: " + cmd.name, text.substr(start, pos - start));
                    if (cmd.name.rfind("\\if", 0) == 0) conditions.push_back(std::nullopt);
                }
            }
        }
        if (wrapped && !ended) throw std::runtime_error("Missing end{document}");
    }

    void assign_ids(std::size_t index, int depth) {
        if (depth > 256) throw std::runtime_error("Hierarchy depth exceeds 256");
        auto& node = nodes[index];
        std::vector<std::string> children;
        for (auto child : node.children) { assign_ids(child, depth + 1); children.push_back(nodes[child].id); }
        // Compact UTF-8 JSON arrays specify the hash input unambiguously.
        Json payload = Json::array({node.kind, node.content});
        if (node.kind != "sentence" && node.kind != "formula" && node.kind != "figure") payload.push_back(children);
        auto key = arxiv_id;
        std::replace(key.begin(), key.end(), '.', '-');
        std::replace(key.begin(), key.end(), '/', '-');
        node.id = key + "#" + node.kind + "-" + digest(payload.dump()).substr(0, 16);
    }

    void export_nodes(std::size_t index, std::set<std::string>& elements_seen,
                      std::set<std::pair<std::string, std::string>>& edges_seen) {
        const auto& node = nodes[index];
        if (elements_seen.insert(node.id).second) {
            result.elements.push_back({node.id, arxiv_id, node.kind, node.content});
            for (auto child : node.children) result.ordered_children[node.id].push_back(nodes[child].id);
        }
        for (auto child : node.children) {
            const auto edge = std::make_pair(nodes[child].id, node.id);
            if (edges_seen.insert(edge).second) result.hierarchy.push_back({arxiv_id, version, edge.first, edge.second});
            export_nodes(child, elements_seen, edges_seen);
        }
    }
};

}  // namespace

HierarchyParser::HierarchyParser(std::string arxiv_id, int version,
                                 const std::filesystem::path& mapping_path)
    : arxiv_id_(std::move(arxiv_id)), version_(version) {
    if (arxiv_id_.empty() || version < 1) throw std::invalid_argument("arxiv_id is required and version must be positive");
    std::ifstream input(mapping_path);
    if (!input) throw std::runtime_error("Cannot read mapping: " + mapping_path.string());
    input >> mapping_;
    // Resolved parser policies: use existing kinds; no table/schema changes.
    for (const auto* name : {"enumerate", "description"})
        mapping_["environments"][name] = mapping_.at("environments").at("itemize");
    mapping_["environments"]["abstract"] = {{"kind", "section"}, {"level", 2}};
}

ParseResult HierarchyParser::parse(const std::string& latex) const {
    return Engine(mapping_, latex, arxiv_id_, version_).run();
}

}  // namespace arxiv::parse

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
    int braces = 0;
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
            if (opening == '[' && c == '{') ++braces;
            if (opening == '[' && c == '}') --braces;
            if (c == opening && braces == 0) ++depth;
            if (c == closing && braces == 0) {
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
                           const std::string& name, const std::set<std::string>& literal) {
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
                    if (literal.count(arg.text)) pos = environment_at(text, pos, arg.text, literal).end;
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

// Whitespace in inline verbatim is visible content, even inside a sentence.
std::string compact_prose(const std::string& source, const std::set<std::string>& literal = {}) {
    std::string out;
    bool gap = false;
    for (std::size_t pos = 0; pos < source.size();) {
        if (space(source[pos])) { gap = !out.empty(); ++pos; continue; }
        if (gap) out += ' ';
        gap = false;
        if (source[pos] == '\\') {
            const auto start = pos;
            const auto cmd = command_at(source, pos);
            pos = cmd.end;
            if (cmd.name == "\\verb" || cmd.name == "\\verb*") pos = verb_end(source, pos);
            else if (cmd.name == "\\begin" && !literal.empty()) {
                const auto name = group_at(source, pos);
                if (literal.count(name.text)) pos = environment_at(source, name.end, name.text, literal).end;
            }
            out += source.substr(start, pos - start);
        } else out += source[pos++];
    }
    return out;
}

std::string without_comments(const std::string& source) {
    std::string out;
    for (std::size_t pos = 0; pos < source.size();) {
        if (source[pos] == '%') {
            const auto end = source.find('\n', pos);
            pos = end == std::string::npos ? source.size() : end + 1;
        } else if (source[pos] == '\\') {
            const auto start = pos;
            const auto cmd = command_at(source, pos);
            pos = cmd.end;
            if (cmd.name == "\\verb" || cmd.name == "\\verb*") pos = verb_end(source, pos);
            out += source.substr(start, pos - start);
        } else out += source[pos++];
    }
    return out;
}

struct Arguments {
    std::vector<std::string> required;
    std::vector<std::string> optional;
    std::string required_source;
    std::vector<std::size_t> required_offsets;
    std::vector<std::size_t> optional_offsets;
    std::size_t end;
};

Arguments arguments_at(const std::string& source, std::size_t pos, const Json& rule,
                       int required_default = 0, int optional_default = 0) {
    Arguments out{{}, {}, "", {}, {}, pos};
    auto read = [&](bool optional) {
        const auto next = skip_space(source, out.end);
        if (optional && (next == source.size() || source[next] != '[')) return;
        const auto group = group_at(source, next, optional ? '[' : '{');
        (optional ? out.optional : out.required).push_back(source.substr(next + 1, group.end - next - 2));
        (optional ? out.optional_offsets : out.required_offsets).push_back(next + 1);
        if (!optional) out.required_source += "{" + group.text + "}";
        out.end = group.end;
    };
    if (rule.contains("argument_spec")) {
        for (const auto& slot : rule.at("argument_spec")) read(slot == "optional");
    } else {
        for (int i = 0; i < rule.value("optional_arguments", optional_default); ++i) read(true);
        for (int i = 0; i < rule.value("arguments", required_default); ++i) read(false);
    }
    return out;
}

struct MathRegion {
    std::string body;
    std::size_t end;
    bool block;
};

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
        : mapping(mapping), text(latex), arxiv_id(arxiv_id), version(version) {
        for (const auto& [name, rule] : mapping.at("environments").items())
            if (rule.value("action", "") == "literal" || name == "comment") literal_names.insert(name);
    }

    ParseResult run() {
        if (compact(text).empty()) return {};
        nodes.push_back({"document", "", 0, {}, ""});
        headings.push_back(0);
        std::size_t pos = 0;
        try {
            pos = body_start();
            parse_body(pos);
            if (!lists.empty()) throw std::runtime_error("Unclosed list environment");
            if (!containers.empty()) throw std::runtime_error("Unclosed container environment");
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
    struct Container {
        std::string name;
        std::string action;
        bool paragraph_boundary;
        std::vector<std::size_t> saved_headings;
    };
    std::vector<Container> containers;
    std::set<std::string> literal_names;
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
            const auto sentence = compact_prose(prose.substr(start, pos + 1 - start));
            if (!sentence.empty()) add("sentence", sentence);
            start = pos + 1;
        }
        const auto tail = compact_prose(prose.substr(start));
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
                    pos = environment_at(text, pos, group.text, literal_names).end;
                }
            }
        }
        if (declared) throw std::runtime_error("Missing begin{document}");
        return 0;
    }

    void heading(const Json& rule, const std::string& title, std::size_t offset,
                 std::optional<std::size_t> title_offset = std::nullopt) {
        flush();
        const int level = rule.at("level");
        if (excluded_level && level > *excluded_level) return;
        excluded_level.reset();
        const auto normalized = normalize(title, "heading", 0, true, title_offset);
        const auto title_key = lower(normalized);
        for (const auto& excluded : mapping.at("exclusions").at("heading_titles")) {
            if (title_key == lower(excluded.get<std::string>())) { excluded_level = level; return; }
        }
        if (!lists.empty()) {
            issue("heading_inside_list", offset, "Heading inside an item needs explicit hierarchy rules", title);
            return;
        }
        while (headings.size() > 1 && nodes[headings.back()].level >= level) headings.pop_back();
        if (headings.size() >= 256) throw std::runtime_error("Hierarchy depth exceeds 256");
        headings.push_back(add(rule.at("kind"), normalized, level));
    }

    std::optional<MathRegion> math_at(const std::string& source, std::size_t pos) const {
        // Block openers precede inline openers, so $$ is never read as two $ tokens.
        for (const auto* category : {"block", "inline"}) {
            for (const auto& rule : mapping.at("math_delimiters").at(category)) {
                const auto opening = rule.at("open").get<std::string>();
                if (source.compare(pos, opening.size(), opening) != 0) continue;
                const auto closing = rule.at("close").get<std::string>();
                const auto body_start = pos + opening.size();
                auto end = body_start;
                while (end < source.size()) {
                    if (source.compare(end, closing.size(), closing) == 0)
                        return MathRegion{source.substr(body_start, end - body_start), end + closing.size(), std::string(category) == "block"};
                    if (source[end] == '%') {
                        const auto newline = source.find('\n', end);
                        end = newline == std::string::npos ? source.size() : newline + 1;
                    } else if (source[end] == '\\') end = command_at(source, end).end;
                    else ++end;
                }
                throw std::runtime_error("Unclosed math delimiter: " + opening);
            }
        }
        return std::nullopt;
    }

    std::string math_content(const std::string& body, bool block) {
        const auto target = mapping.at("normalization_targets").at(block ? "block_math" : "inline_math").get<std::string>();
        const auto marker = target.find("...");
        if (marker == std::string::npos) throw std::runtime_error("Math normalization target needs ... placeholder");
        return target.substr(0, marker) + normalize(body, "formula") + target.substr(marker + 3);
    }

    bool applies(const Json& rule, const std::string& context) const {
        return !rule.contains("contexts") || contains(rule.at("contexts"), context);
    }

    std::string action_of(const Json& rule) const {
        // Keep support for older custom heading rules supplied through the public API.
        if (rule.contains("action")) return rule.at("action");
        return rule.contains("level") ? "heading" : "";
    }

    std::string normalize(const std::string& source, const std::string& context, int depth = 0,
                          bool trim = true, std::optional<std::size_t> source_offset = std::nullopt) {
        if (depth > 128) throw std::runtime_error("Normalization depth exceeds 128");
        std::string out;
        bool gap = false;
        auto emit = [&](const std::string& value, bool literal = false) {
            for (char c : value) {
                if (!literal && space(c)) { gap = !out.empty() || !trim; continue; }
                if (gap) out += ' ';
                out += c;
                gap = false;
            }
        };
        for (std::size_t pos = 0; pos < source.size();) {
            if (source[pos] == '%') {
                const auto end = source.find('\n', pos);
                pos = end == std::string::npos ? source.size() : end + 1;
                continue;
            }
            if (context != "formula") {
                if (const auto math = math_at(source, pos)) {
                    emit(math_content(math->body, math->block));
                    pos = math->end;
                    continue;
                }
            }
            if (source[pos] != '\\') { emit(source.substr(pos++, 1)); continue; }
            const auto start = pos;
            const auto cmd = command_at(source, pos);
            pos = cmd.end;
            if (cmd.name == "\\verb" || cmd.name == "\\verb*") {
                pos = verb_end(source, pos);
                emit(source.substr(start, pos - start), true);
                continue;
            }
            if (cmd.name == "\\begin") {
                const auto name = group_at(source, pos);
                const auto& rules = mapping.at("environments");
                if (rules.contains(name.text)) {
                    const auto& rule = rules.at(name.text);
                    const auto action = rule.value("action", "");
                    if (action == "exclude") {
                        pos = environment_at(source, name.end, name.text, literal_names).end;
                        continue;
                    }
                    if (context != "formula" && (action == "formula" || action == "inline_math")) {
                        const auto args = arguments_at(source, name.end, rule);
                        const auto env = environment_at(source, args.end, name.text, literal_names);
                        emit(action == "formula" ? formula_content(env.body, rule, args) : math_content(env.body, false));
                        pos = env.end;
                        continue;
                    }
                }
                if (rules.contains(name.text) && rules.at(name.text).value("action", "") == "literal") {
                    const auto args = arguments_at(source, name.end, rules.at(name.text));
                    const auto env = environment_at(source, args.end, name.text, literal_names);
                    emit(source.substr(start, args.end - start));
                    emit(env.body, true);
                    emit("\\end{" + name.text + "}");
                    pos = env.end;
                    continue;
                }
            }
            const auto& rules = mapping.at("commands");
            if (!rules.contains(cmd.name) || !applies(rules.at(cmd.name), context)) {
                if (source_offset && context != "formula") {
                    pos = arguments_end(source, pos);
                    issue("unhandled_command", *source_offset + start,
                          "Command preserved without macro expansion: " + cmd.name, source.substr(start, pos - start));
                    emit(without_comments(source.substr(start, pos - start)), true);
                } else emit(cmd.name);
                continue;
            }
            const auto& rule = rules.at(cmd.name);
            const auto action = action_of(rule);
            if (action != "discard" && action != "unwrap" && action != "preserve" && action != "paragraph_break") {
                emit(cmd.name);
                continue;
            }
            const auto args = arguments_at(source, pos, rule);
            pos = args.end;
            if (action == "unwrap") {
                for (std::size_t i = 0; i < args.required.size(); ++i)
                    emit(normalize(args.required[i], context, depth + 1, false,
                         source_offset ? std::optional<std::size_t>(*source_offset + args.required_offsets[i]) : std::nullopt), true);
            } else if (action == "preserve") {
                // Citation keys, URLs and references are semantic arguments, not formatting.
                emit(without_comments(source.substr(start, pos - start)));
            } else if (action == "paragraph_break") emit(" ");
        }
        if (gap && !trim) out += ' ';
        return trim ? compact_prose(out, literal_names) : out;
    }

    std::string formula_content(const std::string& body, const Json& rule, const Arguments& args) {
        auto content = normalize(body, "formula");
        if (rule.contains("inner_environment")) {
            const auto inner = rule.at("inner_environment").get<std::string>();
            std::string argument;
            if (rule.contains("inner_argument")) argument = rule.at("inner_argument");
            if (rule.contains("inner_argument_from")) argument = normalize(args.required.at(rule.at("inner_argument_from").get<std::size_t>()), "formula");
            content = "\\begin{" + inner + "}" + (argument.empty() ? "" : "{" + argument + "}") + content + "\\end{" + inner + "}";
        }
        const auto target = rule.at("normalize_to").get<std::string>();
        return "\\begin{" + target + "}" + content + "\\end{" + target + "}";
    }

    void parse_body(std::size_t& pos) {
        while (pos < text.size()) {
            if (text[pos] == '%') {
                const auto end = text.find('\n', pos);
                pos = end == std::string::npos ? text.size() : end + 1;
                continue;
            }
            if (active()) {
                if (const auto math = math_at(text, pos)) {
                    pos = math->end;
                    if (math->block) {
                        flush();
                        if (!excluded_level) add("formula", math_content(math->body, true));
                    } else append(math_content(math->body, false), true);
                    continue;
                }
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
                if (definitions.count(cmd.name)) pos = definition_end(text, cmd);
                else if (cmd.name == "\\verb" || cmd.name == "\\verb*") pos = verb_end(text, pos);
                else if (cmd.name.rfind("\\if", 0) == 0) conditions.push_back(std::nullopt);
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
            if (cmd.name == "\\begin") {
                const auto group = group_at(text, pos);
                pos = group.end;
                const auto name = group.text;
                const auto& rules = mapping.at("environments");
                if (contains(mapping.at("exclusions").at("environments"), name)) {
                    pos = environment_at(text, pos, name, literal_names).end;
                    continue;
                }
                if (!rules.contains(name)) {
                    const auto env = environment_at(text, pos, name, literal_names);
                    pos = env.end;
                    if (!excluded_level) {
                        flush();
                        issue("unhandled_environment", start, "Environment has no settled mapping: " + name, text.substr(start, pos - start));
                    }
                    continue;
                }
                const auto& rule = rules.at(name);
                const auto action = action_of(rule);
                if (action == "exclude") {
                    pos = environment_at(text, pos, name, literal_names).end;
                    continue;
                }
                if (action == "root") throw std::runtime_error("Nested document environment");
                const auto args = arguments_at(text, pos, rule);
                pos = args.end;
                if (excluded_level) {
                    pos = environment_at(text, pos, name, literal_names).end;
                    continue;
                }
                if (action == "inline_math") {
                    const auto env = environment_at(text, pos, name, literal_names);
                    append(math_content(env.body, false), true);
                    pos = env.end;
                    continue;
                }
                const bool boundary = rule.value("paragraph_boundary", true);
                if (boundary) flush();
                if (action == "list" || action == "heading" || action == "transparent") {
                    if (containers.size() >= 128) throw std::runtime_error("Container depth exceeds 128");
                    Container frame{name, action, boundary, {}};
                    if (action == "list") lists.push_back({name, add(rule.at("kind"), rule.value("content", "")), std::nullopt});
                    if (action == "heading") {
                        if (!lists.empty()) throw std::runtime_error("Heading environment inside a list");
                        frame.saved_headings = headings;
                        if (rule.value("parent", "") == "document") headings = {0};
                        heading(rule, rule.at("content"), start);
                    }
                    containers.push_back(std::move(frame));
                    if (rule.value("optional_argument_content", "") == "prepend")
                        for (std::size_t i = 0; i < args.optional.size(); ++i) {
                            if (rule.contains("optional_argument_indices")) {
                                const auto& selected = rule.at("optional_argument_indices");
                                if (std::find(selected.begin(), selected.end(), Json(i)) == selected.end()) continue;
                            }
                            append(normalize(args.optional[i], "prose", 0, true, args.optional_offsets[i]) + " ", true);
                        }
                    continue;
                }
                const auto env = environment_at(text, pos, name, literal_names);
                pos = env.end;
                if (action == "formula") add(rule.at("kind"), formula_content(env.body, rule, args));
                else if (action == "figure")
                    add(rule.at("kind"), "\\begin{" + name + "}" + normalize(args.required_source + env.body, "figure") + "\\end{" + name + "}");
                else if (action == "literal") add(rule.at("kind"), env.body);
                else issue("unhandled_environment", start, "Unsupported mapping action: " + action, text.substr(start, pos - start));
                continue;
            }
            if (cmd.name == "\\end") {
                const auto group = group_at(text, pos);
                pos = group.end;
                if (group.text == "document" && wrapped) {
                    if (!containers.empty()) throw std::runtime_error("Document ended inside an open container");
                    ended = true;
                    break;
                }
                if (containers.empty() || group.text != containers.back().name)
                    throw std::runtime_error("Unexpected end{" + group.text + "}");
                const auto frame = containers.back();
                if (frame.paragraph_boundary) flush();
                if (frame.action == "list") lists.pop_back();
                if (frame.action == "heading") headings = frame.saved_headings;
                containers.pop_back();
                continue;
            }
            const auto& rules = mapping.at("commands");
            if (rules.contains(cmd.name) && applies(rules.at(cmd.name), "prose")) {
                const auto& rule = rules.at(cmd.name);
                const auto action = action_of(rule);
                const auto args = arguments_at(text, pos, rule, action == "heading" ? 1 : 0,
                                               action == "heading" || action == "item" ? 1 : 0);
                pos = args.end;
                if (excluded_level && action != "heading") continue;
                if (action == "heading") heading(rule, args.required.at(0), start, args.required_offsets.at(0));
                else if (action == "item" && !excluded_level) {
                    flush();
                    if (lists.empty()) throw std::runtime_error("Item outside list");
                    const auto index = nodes.size();
                    nodes[lists.back().node].children.push_back(index);
                    nodes.push_back({rule.at("kind"), rule.value("content", ""), 0, {}, ""});
                    lists.back().item = index;
                    if (rule.value("optional_label", "") == "preserve_in_first_sentence")
                        for (std::size_t i = 0; i < args.optional.size(); ++i)
                            append(normalize(args.optional[i], "prose", 0, true, args.optional_offsets[i]) + " ", true);
                } else if (action == "paragraph_break") flush();
                else if (action == "unwrap") {
                    for (std::size_t i = 0; i < args.required.size(); ++i)
                        append(normalize(args.required[i], "prose", 0, false, args.required_offsets[i]), true);
                } else if (action == "preserve") append(normalize(text.substr(start, pos - start), "prose"), true);
                else if (action != "discard" && !excluded_level)
                    issue("unhandled_command", start, "Unsupported mapping action: " + action, text.substr(start, pos - start));
            } else if (cmd.name == "\\appendix") {
                flush();
                excluded_level.reset();
            } else if (contains(mapping.at("exclusions").at("commands"), cmd.name)) {
                pos = arguments_end(text, pos);
            } else if (cmd.name == "\\endinput") {
                break;
            } else {
                pos = arguments_end(text, pos);
                if (!excluded_level) {
                    append(without_comments(text.substr(start, pos - start)), true);
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

}

ParseResult HierarchyParser::parse(const std::string& latex) const {
    return Engine(mapping_, latex, arxiv_id_, version_).run();
}

}  // namespace arxiv::parse

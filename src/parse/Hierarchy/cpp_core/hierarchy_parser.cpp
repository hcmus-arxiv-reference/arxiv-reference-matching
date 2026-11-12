#include "hierarchy_parser.hpp"

#include <algorithm>
#include <cctype>
#include <fstream>
#include <functional>
#include <iomanip>
#include <numeric>
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
        while (end < text.size() && (static_cast<unsigned char>(text[end]) & 0xc0) == 0x80) ++end;
    }
    return {text.substr(start, end - start), end};
}

bool control_word_before(const std::string& text, std::size_t end) {
    const auto last = end;
    while (end > 0 && (letter(text[end - 1]) || text[end - 1] == '@')) --end;
    if (end == last) return false;
    const auto word = end;
    while (end > 0 && text[end - 1] == '\\') --end;
    return (word - end) % 2 == 1;
}

void append_tokens(std::string& out, const std::string& value) {
    // TeX expands token lists: replacing an adjacent macro must not form \alphab.
    if (!value.empty() && (letter(value[0]) || value[0] == '@') && control_word_before(out, out.size())) out += ' ';
    out += value;
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
                           const std::string& name, const std::set<std::string>& literal,
                           const std::function<bool(const Command&, std::size_t, std::size_t&)>& expand = {}) {
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
            } else if (expand && expand(cmd, start, pos)) {
                continue;
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
        if (!optional && rule.value("token_arguments", false) && next < source.size() && source[next] != '{') {
            auto end = source[next] == '\\' ? command_at(source, next).end : next + 1;
            // Consume one UTF-8 code point rather than one byte for an unbraced token.
            while (end < source.size() && (static_cast<unsigned char>(source[end]) & 0xc0) == 0x80) ++end;
            out.required.push_back(source.substr(next, end - next));
            out.required_offsets.push_back(next);
            out.required_source += "{" + out.required.back() + "}";
            out.end = end;
            return;
        }
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

struct CounterGuard {
    int& value;
    int delta;
    explicit CounterGuard(int& value, int delta = 1) : value(value), delta(delta) { value += delta; }
    ~CounterGuard() { value -= delta; }
};

class Engine {
public:
    Engine(const Json& mapping, const std::string& latex, const std::string& arxiv_id, int version)
        : mapping(mapping), text(latex), arxiv_id(arxiv_id), version(version), original_size(latex.size()), origins(latex.size()), expansion_depth(latex.size(), 0) {
        std::iota(origins.begin(), origins.end(), 0);
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
            flush();
            if (!lists.empty()) throw std::runtime_error("Unclosed list environment");
            if (!containers.empty()) throw std::runtime_error("Unclosed container environment");
            if (!conditions.empty()) throw std::runtime_error("Unclosed conditional");
            if (!scopes.empty()) { pos = scopes.back().offset; throw std::runtime_error("Unclosed group"); }
        } catch (const std::runtime_error& error) {
            issue("invalid_syntax", pos, error.what(), "");
            // A later unsupported construct must not erase the valid prose prefix.
            try { flush(); }
            catch (const std::runtime_error& recovery_error) {
                issue("invalid_syntax", pos, "Cannot recover pending prose: " + std::string(recovery_error.what()), prose);
            }
        }
        assign_ids(0, 0);
        std::set<std::string> elements_seen;
        std::set<std::pair<std::string, std::string>> edges_seen;
        export_nodes(0, elements_seen, edges_seen);
        return std::move(result);
    }

private:
    const Json& mapping;
    std::string text;
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
    // Each expanded byte points back to its invocation in the original merged source.
    std::size_t original_size;
    std::vector<std::size_t> origins;
    std::vector<int> expansion_depth;
    struct Macro { int count; std::optional<std::string> fallback; std::string body; bool supported; };
    std::map<std::string, Macro> macros;
    Json declared_environments = Json::object();
    std::map<std::string, bool> booleans;
    struct Scope { std::map<std::string, Macro> macros; Json environments; std::map<std::string, bool> booleans; std::size_t offset; };
    std::vector<Scope> scopes;
    std::size_t expansions = 0;
    int normalization_depth = 0;
    int opaque_figures = 0;

    void issue(const std::string& code, std::size_t offset, const std::string& message,
               const std::string& source) {
        result.diagnostics.push_back({code, offset < origins.size() ? origins[offset] : original_size, message, source});
    }

    void open_scope(std::size_t offset) {
        if (scopes.size() >= 256) throw std::runtime_error("Group depth exceeds 256");
        scopes.push_back({macros, declared_environments, booleans, offset});
    }

    void close_scope() {
        if (scopes.empty()) throw std::runtime_error("Unmatched closing group");
        macros = std::move(scopes.back().macros);
        declared_environments = std::move(scopes.back().environments);
        booleans = std::move(scopes.back().booleans);
        scopes.pop_back();
    }

    bool boolean_command(const Command& cmd, std::size_t& pos) {
        if (cmd.name == "\\newif") {
            pos = skip_space(text, pos);
            if (pos >= text.size() || text[pos] != '\\') throw std::runtime_error("Expected a newif control sequence");
            const auto target = command_at(text, pos);
            if (target.name.rfind("\\if", 0) != 0) throw std::runtime_error("Expected an if-prefixed control sequence");
            pos = target.end;
            if (active()) booleans[target.name] = false;
            return true;
        }
        for (auto& [name, value] : booleans) {
            const auto stem = "\\" + name.substr(3);
            if (cmd.name == stem + "true" || cmd.name == stem + "false") {
                if (active()) value = cmd.name == stem + "true";
                return true;
            }
        }
        return false;
    }

    bool declaration(const Command& cmd, std::size_t& pos, bool report) {
        if (cmd.name == "\\newtheorem" || cmd.name == "\\newtheorem*") {
            const auto name = group_at(text, pos);
            pos = skip_space(text, name.end);
            if (pos < text.size() && text[pos] == '[') pos = group_at(text, pos, '[').end;
            pos = group_at(text, pos).end; // Printed label is generated by TeX, not a heading.
            const auto next = skip_space(text, pos);
            if (next < text.size() && text[next] == '[') pos = group_at(text, next, '[').end;
            if (mapping.contains("declarations") && mapping.at("declarations").contains("newtheorem"))
                declared_environments[name.text] = mapping.at("declarations").at("newtheorem");
            return true;
        }
        if (!definitions.count(cmd.name)) return false;
        const auto start = cmd.end - cmd.name.size();
        const auto end = definition_end(text, cmd);
        if (cmd.name.find("environment") != std::string::npos) {
            pos = end;
            if (report) issue("unexpanded_definition", start, "Custom environment definitions are not executed", text.substr(start, end - start));
            return true;
        }
        auto next = skip_space(text, cmd.end);
        std::string name;
        if (next < text.size() && text[next] == '\\') { const auto token = command_at(text, next); name = token.name; next = token.end; }
        else { const auto token = group_at(text, next); name = compact(token.text); next = token.end; }
        int count = 0;
        std::optional<std::string> fallback;
        bool supported = cmd.name != "\\edef" && cmd.name != "\\xdef" && cmd.name != "\\gdef";
        next = skip_space(text, next);
        if (cmd.name == "\\def" || cmd.name == "\\edef" || cmd.name == "\\xdef" || cmd.name == "\\gdef") {
            const auto brace = text.find('{', next);
            const auto signature = without_comments(text.substr(next, brace - next));
            std::string expected;
            for (char c : signature) if (c >= '1' && c <= '9') count = std::max(count, c - '0');
            for (int i = 1; i <= count; ++i) expected += "#" + std::to_string(i);
            supported = supported && signature == expected;
            next = brace;
        } else if (next < text.size() && text[next] == '[') {
            const auto arity = group_at(text, next, '[');
            const auto number = compact(arity.text);
            supported = number.size() == 1 && digit(number[0]);
            count = supported ? number[0] - '0' : 0;
            next = skip_space(text, arity.end);
            if (next < text.size() && text[next] == '[') {
                const auto value = group_at(text, next, '[');
                fallback = value.text;
                next = value.end;
                supported = supported && count > 0;
            }
        }
        const auto body = group_at(text, next);
        for (std::size_t i = 0; i < body.text.size(); ++i) {
            if (body.text[i] == '\\') { i = command_at(body.text, i).end - 1; continue; }
            if (body.text[i] == '#' && (i + 1 == body.text.size() || body.text[i + 1] < '1' || body.text[i + 1] > '0' + count)) supported = false;
        }
        supported = supported && mapping.contains("declarations") && mapping.at("declarations").contains("macros") && mapping.at("declarations").at("macros").value("enabled", false);
        const bool provide = cmd.name == "\\providecommand" || cmd.name == "\\providecommand*";
        if (!provide || (!macros.count(name) && !mapping.at("commands").contains(name)))
            macros[name] = {count, fallback, body.text, supported};
        pos = end;
        if (!supported && report) issue("unexpanded_definition", start, "Unsupported macro definition: " + name, text.substr(start, end - start));
        return true;
    }

    std::optional<std::pair<std::string, std::size_t>> expansion(const std::string& source, const Command& cmd, int depth) {
        const auto found = macros.find(cmd.name);
        if (found == macros.end() || !found->second.supported) return std::nullopt;
        const auto& limits = mapping.at("declarations").at("macros");
        if (depth >= limits.value("max_depth", 64) || ++expansions > limits.value("max_expansions", 100000U))
            throw std::runtime_error("Macro expansion limit reached: " + cmd.name);
        const auto& macro = found->second;
        Json rule = {{"arguments", macro.count - (macro.fallback ? 1 : 0)}, {"optional_arguments", macro.fallback ? 1 : 0}, {"token_arguments", true}};
        auto args = arguments_at(source, cmd.end, rule);
        std::vector<std::string> values;
        if (macro.fallback) values.push_back(args.optional.empty() ? *macro.fallback : args.optional.front());
        values.insert(values.end(), args.required.begin(), args.required.end());
        std::string out;
        for (std::size_t i = 0; i < macro.body.size(); ++i) {
            if (macro.body[i] == '\\') {
                const auto token = command_at(macro.body, i);
                append_tokens(out, token.name); i = token.end - 1;
            } else if (macro.body[i] == '#' && i + 1 < macro.body.size()) append_tokens(out, values.at(macro.body[++i] - '1'));
            else append_tokens(out, macro.body.substr(i, 1));
            if (out.size() > limits.value("max_expanded_bytes", 8388608U)) throw std::runtime_error("Expanded macro exceeds byte limit");
        }
        const auto start = cmd.end - cmd.name.size();
        if (!out.empty() && (letter(out[0]) || out[0] == '@') && control_word_before(source, start)) out.insert(0, " ");
        if (args.end < source.size() && (letter(source[args.end]) || source[args.end] == '@') && control_word_before(out, out.size())) out += ' ';
        return std::make_pair(out, args.end);
    }

    bool expand_body(const Command& cmd, std::size_t start, std::size_t& pos) {
        const int depth = expansion_depth.at(start);
        const auto expanded = expansion(text, cmd, depth);
        if (!expanded) return false;
        const auto& [value, end] = *expanded;
        if (text.size() - (end - start) + value.size() > mapping.at("declarations").at("macros").value("max_expanded_bytes", 8388608U))
            throw std::runtime_error("Expanded document exceeds byte limit");
        const auto origin = origins.at(start);
        text.replace(start, end - start, value);
        origins.erase(origins.begin() + start, origins.begin() + end);
        origins.insert(origins.begin() + start, value.size(), origin);
        expansion_depth.erase(expansion_depth.begin() + start, expansion_depth.begin() + end);
        expansion_depth.insert(expansion_depth.begin() + start, value.size(), depth + 1);
        pos = start;
        return true;
    }

    void unwrap_body(const Arguments& args, const Json& rule, std::size_t start, std::size_t& pos) {
        for (std::size_t i = 0; i < args.required.size(); ++i) {
            if (rule.contains("content_arguments")) {
                const auto& selected = rule.at("content_arguments");
                if (std::find(selected.begin(), selected.end(), Json(i)) == selected.end()) continue;
            }
            const auto& part = args.required[i];
            const auto& commands = mapping.at("commands");
            if (commands.contains(part) && action_of(commands.at(part)) == "heading" &&
                !commands.at(part).contains("fixed_title")) {
                issue("unhandled_command", start, "Heading token without its argument inside a prose wrapper", text.substr(start, pos - start));
                append(text.substr(start, pos - start) + " ", true);
                return;
            }
        }
        std::string value;
        std::vector<std::size_t> value_origins;
        std::vector<int> value_depths;
        const auto origin = origins.at(start);
        const auto depth = std::max(1, expansion_depth.at(start));
        auto literal = [&](const std::string& part) {
            value += part;
            value_origins.insert(value_origins.end(), part.size(), origin);
            value_depths.insert(value_depths.end(), part.size(), depth);
        };
        auto argument = [&](const std::string& part, std::size_t offset) {
            // Plain groups preserve argument-local definitions and token boundaries.
            // They also let xspace see the actual argument end, before punctuation.
            literal("{");
            value += part;
            value_origins.insert(value_origins.end(), origins.begin() + offset, origins.begin() + offset + part.size());
            for (std::size_t i = offset; i < offset + part.size(); ++i)
                value_depths.push_back(std::max(1, expansion_depth[i]));
            literal("}");
        };
        auto selected = [&](const char* key, std::size_t i, bool fallback) {
            if (!rule.contains(key)) return fallback;
            const auto& entries = rule.at(key);
            return std::find(entries.begin(), entries.end(), Json(i)) != entries.end();
        };
        literal(rule.value("content_prefix", ""));
        for (std::size_t i = 0; i < args.required.size(); ++i)
            if (selected("content_arguments", i, true)) argument(args.required[i], args.required_offsets[i]);
        for (std::size_t i = 0; i < args.optional.size(); ++i)
            if (selected("content_optional_arguments", i, false)) argument(args.optional[i], args.optional_offsets[i]);
        literal(rule.value("content_suffix", ""));
        const auto limit = mapping.value("declarations", Json::object()).value("macros", Json::object()).value("max_expanded_bytes", 8388608U);
        if (text.size() - (pos - start) + value.size() > limit) throw std::runtime_error("Unwrapped document exceeds byte limit");
        text.replace(start, pos - start, value);
        origins.erase(origins.begin() + start, origins.begin() + pos);
        origins.insert(origins.begin() + start, value_origins.begin(), value_origins.end());
        expansion_depth.erase(expansion_depth.begin() + start, expansion_depth.begin() + pos);
        expansion_depth.insert(expansion_depth.begin() + start, value_depths.begin(), value_depths.end());
        pos = start;
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
        try {
            for (std::size_t pos = 0; pos < text.size();) {
                if (text[pos] == '%') {
                    const auto end = text.find('\n', pos);
                    pos = end == std::string::npos ? text.size() : end + 1;
                } else if (text[pos] != '\\') {
                    if (active() && text[pos] == '{') open_scope(pos);
                    else if (active() && text[pos] == '}') close_scope();
                    ++pos;
                } else {
                    const auto cmd = command_at(text, pos);
                    pos = cmd.end;
                    if (boolean_command(cmd, pos)) continue;
                    if (booleans.count(cmd.name)) { conditions.push_back(booleans.at(cmd.name)); continue; }
                    if (cmd.name == "\\iftrue" || cmd.name == "\\iffalse") { conditions.push_back(cmd.name == "\\iftrue"); continue; }
                    if (cmd.name.rfind("\\if", 0) == 0 && cmd.name != "\\ifthenelse") { conditions.push_back(std::nullopt); continue; }
                    if (cmd.name == "\\else" && !conditions.empty()) { if (conditions.back()) conditions.back() = !*conditions.back(); continue; }
                    if (cmd.name == "\\fi" && !conditions.empty()) { conditions.pop_back(); continue; }
                    if (!active()) { if (definitions.count(cmd.name)) pos = definition_end(text, cmd); continue; }
                    if (declaration(cmd, pos, false)) continue;
                    else if (cmd.name == "\\verb" || cmd.name == "\\verb*") pos = verb_end(text, pos);
                    else if (cmd.name == "\\begingroup" || cmd.name == "\\bgroup") open_scope(pos - cmd.name.size());
                    else if (cmd.name == "\\endgroup" || cmd.name == "\\egroup") close_scope();
                    else if (cmd.name == "\\documentclass") declared = true;
                    else if (cmd.name == "\\begin") {
                        const auto group = group_at(text, pos);
                        pos = group.end;
                        if (group.text == "document") { wrapped = true; return pos; }
                        pos = environment_at(text, pos, group.text, literal_names).end;
                    } else pos = arguments_end(text, pos);
                }
            }
            if (declared) throw std::runtime_error("Missing begin{document}");
        } catch (const std::runtime_error&) {
            // This scan only probes for a document wrapper. Let the actual fragment
            // parse report a malformed suffix after preserving its valid prefix.
            if (declared) throw;
        }
        // A fragment is parsed again from byte zero; do not retain declarations from this scan.
        macros.clear(); declared_environments = Json::object(); booleans.clear(); scopes.clear(); conditions.clear();
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
                int brace_depth = 0;
                while (end < source.size()) {
                    if (brace_depth == 0 && source.compare(end, closing.size(), closing) == 0)
                        return MathRegion{source.substr(body_start, end - body_start), end + closing.size(), std::string(category) == "block"};
                    if (source[end] == '%') {
                        const auto newline = source.find('\n', end);
                        end = newline == std::string::npos ? source.size() : newline + 1;
                    } else if (source[end] == '\\') end = command_at(source, end).end;
                    else {
                        if (source[end] == '{') ++brace_depth;
                        else if (source[end] == '}' && brace_depth > 0) --brace_depth;
                        ++end;
                    }
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

    std::string replacement_content(const Json& rule, const std::string& source, std::size_t pos) {
        if (rule.contains("omit_before")) {
            auto next = skip_space(source, pos);
            while (source.compare(next, 2, "{}") == 0) next = skip_space(source, next + 2);
            if (next == source.size() || rule.at("omit_before").get<std::string>().find(source[next]) != std::string::npos) return "";
        }
        return rule.at("replacement");
    }

    std::string command_content(const Arguments& args, const Json& rule, const std::string& context,
                                int depth, std::optional<std::size_t> source_offset,
                                const std::vector<std::size_t>* positions = nullptr) {
        std::string out = rule.value("content_prefix", "");
        auto selected = [&](const char* key, std::size_t i, bool default_value) {
            if (!rule.contains(key)) return default_value;
            const auto& indices = rule.at(key);
            return std::find(indices.begin(), indices.end(), Json(i)) != indices.end();
        };
        auto content = [&](const std::string& value, std::size_t offset) {
            std::vector<std::size_t> child_positions;
            if (positions && !positions->empty())
                child_positions.assign(positions->begin() + offset, positions->begin() + offset + value.size());
            return normalize(value, context, depth + 1, false,
                source_offset ? std::optional<std::size_t>(*source_offset + offset) : std::nullopt,
                child_positions.empty() ? nullptr : &child_positions);
        };
        for (std::size_t i = 0; i < args.required.size(); ++i)
            if (selected("content_arguments", i, true)) out += content(args.required[i], args.required_offsets[i]);
        for (std::size_t i = 0; i < args.optional.size(); ++i)
            if (selected("content_optional_arguments", i, false))
                out += content(args.optional[i], args.optional_offsets[i]);
        out += rule.value("content_suffix", "");
        return out;
    }

    std::string accent_content(const Arguments& args, const Json& rule, const std::string& context, int depth,
                               std::optional<std::size_t> source_offset = std::nullopt,
                               const std::vector<std::size_t>* positions = nullptr) {
        auto body = compact_prose(command_content(args, rule, context, depth, source_offset, positions));
        if (body == "ı") body = "i";
        if (body == "ȷ") body = "j";
        std::size_t first = body.empty() ? 0 : 1;
        while (first < body.size() && (static_cast<unsigned char>(body[first]) & 0xc0) == 0x80) ++first;
        const auto base = body.substr(0, first);
        if (rule.contains("characters") && rule.at("characters").contains(base))
            return rule.at("characters").at(base).get<std::string>() + body.substr(first);
        return base + rule.at("combining_mark").get<std::string>() + body.substr(first);
    }

    std::string normalize(std::string source, const std::string& context, int depth = 0,
                          bool trim = true, std::optional<std::size_t> source_offset = std::nullopt,
                          const std::vector<std::size_t>* source_positions = nullptr) {
        if (depth > 128) throw std::runtime_error("Normalization depth exceeds 128");
        if (normalization_depth >= 128) throw std::runtime_error("Nested normalization exceeds 128");
        CounterGuard depth_guard(normalization_depth);
        CounterGuard figure_guard(opaque_figures, context == "figure" ? 1 : 0);
        std::vector<std::size_t> positions;
        if (source_positions) positions = *source_positions;
        else if (source_offset) { positions.resize(source.size()); std::iota(positions.begin(), positions.end(), *source_offset); }
        std::vector<int> depths(source.size(), depth);
        auto expand_local = [&](const Command& cmd, std::size_t start, std::size_t& pos) {
            if (opaque_figures) return false;
            const auto expanded = expansion(source, cmd, depths.at(start));
            if (!expanded) return false;
            const auto& [value, end] = *expanded;
            if (source.size() - (end - start) + value.size() > mapping.at("declarations").at("macros").value("max_expanded_bytes", 8388608U))
                throw std::runtime_error("Expanded argument exceeds byte limit");
            const auto next_depth = depths[start] + 1;
            if (!positions.empty()) {
                const auto original = positions[start];
                positions.erase(positions.begin() + start, positions.begin() + end);
                positions.insert(positions.begin() + start, value.size(), original);
            }
            source.replace(start, end - start, value);
            depths.erase(depths.begin() + start, depths.begin() + end);
            depths.insert(depths.begin() + start, value.size(), next_depth);
            pos = start;
            return true;
        };
        auto expand_environment = [&](const Command& cmd, std::size_t start, std::size_t& pos) {
            const auto& rules = mapping.at("commands");
            if (!macros.count(cmd.name) && rules.contains(cmd.name) && applies(rules.at(cmd.name), "formula") && action_of(rules.at(cmd.name)) == "preserve") {
                pos = arguments_at(source, pos, rules.at(cmd.name)).end;
                return true;
            }
            return expand_local(cmd, start, pos);
        };
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
            if ((context == "prose" || context == "heading") && (source[pos] == '{' || source[pos] == '}')) { ++pos; continue; }
            if (source[pos] != '\\') { emit(source.substr(pos++, 1)); continue; }
            const auto start = pos;
            const auto cmd = command_at(source, pos);
            pos = cmd.end;
            if (cmd.name == "\\verb" || cmd.name == "\\verb*") {
                pos = verb_end(source, pos);
                emit(source.substr(start, pos - start), true);
                continue;
            }
            if (expand_local(cmd, start, pos)) continue;
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
                    if (action == "figure" && !rule.value("normalize_body", true)) {
                        const auto env = environment_at(source, name.end, name.text, literal_names);
                        emit(without_comments(source.substr(start, env.end - start)), true);
                        pos = env.end;
                        continue;
                    }
                    if (context == "figure" && action == "figure") {
                        const auto args = arguments_at(source, name.end, rule);
                        // Column preambles can contain dollar tokens in separate groups.
                        // They are environment configuration, not standalone math.
                        emit("\\begin{" + name.text + "}" + without_comments(args.required_source), true);
                        pos = args.end;
                        continue;
                    }
                    if (context != "formula" && (action == "formula" || action == "inline_math")) {
                        const auto args = arguments_at(source, name.end, rule);
                        const auto env = environment_at(source, args.end, name.text, literal_names, expand_environment);
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
            if (macros.count(cmd.name) || !rules.contains(cmd.name) || !applies(rules.at(cmd.name), context)) {
                if (source_offset && context != "formula") {
                    pos = arguments_end(source, pos);
                    issue("unhandled_command", positions.at(start),
                          "Command preserved without macro expansion: " + cmd.name, source.substr(start, pos - start));
                    emit(without_comments(source.substr(start, pos - start)), true);
                } else emit(cmd.name);
                continue;
            }
            const auto& rule = rules.at(cmd.name);
            const auto action = action_of(rule);
            if (action != "discard" && action != "unwrap" && action != "preserve" && action != "paragraph_break" && action != "replace" && action != "accent" && action != "inline_math") {
                emit(cmd.name);
                continue;
            }
            const auto args = arguments_at(source, pos, rule);
            pos = args.end;
            if (action == "unwrap") {
                emit(command_content(args, rule, context, depth, source_offset, &positions), true);
            } else if (action == "replace") emit(replacement_content(rule, source, pos));
            else if (action == "accent") emit(accent_content(args, rule, context, depth, source_offset, &positions));
            else if (action == "inline_math") emit(math_content(args.required.at(0), false));
            else if (action == "preserve") {
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
                if (active()) {
                    if (text[pos] == '{') open_scope(pos);
                    else if (text[pos] == '}') close_scope();
                    else append(text.substr(pos, 1), expansion_depth[pos] > 0);
                }
                ++pos;
                continue;
            }
            const auto start = pos;
            const auto cmd = command_at(text, pos);
            pos = cmd.end;
            if (boolean_command(cmd, pos)) continue;
            if (booleans.count(cmd.name)) { conditions.push_back(booleans.at(cmd.name)); continue; }
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
            if (declaration(cmd, pos, !excluded_level)) continue;
            if (cmd.name == "\\begingroup" || cmd.name == "\\bgroup") { open_scope(start); continue; }
            if (cmd.name == "\\endgroup" || cmd.name == "\\egroup") { close_scope(); continue; }
            if (cmd.name == "\\verb" || cmd.name == "\\verb*") {
                pos = verb_end(text, pos);
                append(text.substr(start, pos - start), true);
                continue;
            }
            if (expand_body(cmd, start, pos)) continue;
            if (cmd.name == "\\begin") {
                const auto group = group_at(text, pos);
                pos = group.end;
                const auto name = group.text;
                const auto& rules = mapping.at("environments");
                if (contains(mapping.at("exclusions").at("environments"), name)) {
                    pos = environment_at(text, pos, name, literal_names).end;
                    continue;
                }
                if (!rules.contains(name) && !declared_environments.contains(name)) {
                    const auto env = environment_at(text, pos, name, literal_names);
                    pos = env.end;
                    if (!excluded_level) {
                        flush();
                        issue("unhandled_environment", start, "Environment has no settled mapping: " + name, text.substr(start, pos - start));
                    }
                    continue;
                }
                // A source declaration takes precedence over a generic package name.
                const auto rule = declared_environments.contains(name) ? declared_environments.at(name) : rules.at(name);
                const auto action = action_of(rule);
                if (action == "exclude") {
                    pos = environment_at(text, pos, name, literal_names).end;
                    continue;
                }
                if (action == "root") throw std::runtime_error("Nested document environment");
                const auto args = arguments_at(text, pos, rule);
                pos = args.end;
                if (rule.value("reset_reference_exclusion", false)) excluded_level.reset();
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
                    open_scope(start);
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
                const auto env = environment_at(text, pos, name, literal_names,
                    action != "formula" ? std::function<bool(const Command&, std::size_t, std::size_t&)>{} :
                    [this](const Command& command, std::size_t start, std::size_t& pos) {
                        const auto& rules = mapping.at("commands");
                        if (!macros.count(command.name) && rules.contains(command.name) && applies(rules.at(command.name), "formula") && action_of(rules.at(command.name)) == "preserve") {
                            pos = arguments_at(text, pos, rules.at(command.name)).end;
                            return true;
                        }
                        return expand_body(command, start, pos);
                    });
                pos = env.end;
                if (action == "formula") add(rule.at("kind"), formula_content(env.body, rule, args));
                else if (action == "figure")
                    add(rule.at("kind"), "\\begin{" + name + "}" +
                        (rule.value("normalize_body", true) ? compact_prose(without_comments(args.required_source) + normalize(env.body, "figure", 0, false), literal_names) :
                         compact_prose(without_comments(args.required_source + env.body), literal_names)) + "\\end{" + name + "}");
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
                close_scope();
                continue;
            }
            const auto& rules = mapping.at("commands");
            if (!macros.count(cmd.name) && rules.contains(cmd.name) && applies(rules.at(cmd.name), "prose")) {
                const auto& rule = rules.at(cmd.name);
                const auto action = action_of(rule);
                const auto args = arguments_at(text, pos, rule, action == "heading" ? 1 : 0,
                                               action == "heading" || action == "item" ? 1 : 0);
                pos = args.end;
                if (excluded_level && action != "heading") continue;
                if (action == "heading") {
                    if (rule.contains("fixed_title")) {
                        heading(rule, rule.at("fixed_title"), start);
                        if (rule.contains("body_argument")) {
                            const auto i = rule.at("body_argument").get<std::size_t>();
                            unwrap_body(args, Json{{"content_arguments", Json::array({i})}, {"content_suffix", "\\par{}"}}, start, pos);
                        }
                    } else heading(rule, args.required.at(0), start, args.required_offsets.at(0));
                }
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
                    unwrap_body(args, rule, start, pos);
                } else if (action == "replace") append(replacement_content(rule, text, pos));
                else if (action == "accent") append(accent_content(args, rule, "prose", 0, 0), true);
                else if (action == "inline_math") append(math_content(args.required.at(0), false), true);
                else if (action == "preserve") append(normalize(text.substr(start, pos - start), "prose"), true);
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

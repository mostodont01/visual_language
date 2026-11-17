// A small JSON reader for the VL runtime: enough to read the values file
// (settings and initial input values) a compiled program loads at start-up.
// Nodes may use it too.
#pragma once

#include <cstdint>
#include <locale>
#include <map>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace vl {
namespace json {

class Value {
public:
    enum class Kind { Null, Bool, Number, String, Array, Object };

    Value() = default;
    static Value boolean(bool b) { Value v; v.kind_ = Kind::Bool; v.bool_ = b; return v; }
    static Value number(double d) { Value v; v.kind_ = Kind::Number; v.number_ = d; return v; }
    static Value string(std::string s) { Value v; v.kind_ = Kind::String; v.string_ = std::move(s); return v; }
    static Value array() { Value v; v.kind_ = Kind::Array; return v; }
    static Value object() { Value v; v.kind_ = Kind::Object; return v; }

    Kind kind() const { return kind_; }
    bool isNull() const { return kind_ == Kind::Null; }
    bool isBool() const { return kind_ == Kind::Bool; }
    bool isNumber() const { return kind_ == Kind::Number; }
    bool isString() const { return kind_ == Kind::String; }
    bool isArray() const { return kind_ == Kind::Array; }
    bool isObject() const { return kind_ == Kind::Object; }

    bool asBool() const { return kind_ == Kind::Bool ? bool_ : kind_ == Kind::Number ? number_ != 0 : false; }
    double asNumber() const { return kind_ == Kind::Number ? number_ : kind_ == Kind::Bool ? (bool_ ? 1 : 0) : 0; }
    const std::string& asString() const {
        static const std::string empty;
        return kind_ == Kind::String ? string_ : empty;
    }

    // Arrays.
    const std::vector<Value>& items() const { return items_; }
    void push(Value v) { items_.push_back(std::move(v)); }

    // Objects (keys in sorted order).
    const std::map<std::string, Value>& members() const { return members_; }
    bool has(const std::string& key) const { return members_.count(key) != 0; }
    // The member, or null if there is none (or this isn't an object).
    const Value& operator[](const std::string& key) const {
        static const Value null;
        auto it = members_.find(key);
        return it == members_.end() ? null : it->second;
    }
    void set(const std::string& key, Value v) { members_[key] = std::move(v); }

private:
    Kind kind_ = Kind::Null;
    bool bool_ = false;
    double number_ = 0;
    std::string string_;
    std::vector<Value> items_;
    std::map<std::string, Value> members_;
};

class ParseError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

namespace detail {

class Parser {
public:
    explicit Parser(const std::string& text) : s_(text) {}

    Value document() {
        Value v = value();
        space();
        if (i_ != s_.size())
            fail("unexpected text after the value");
        return v;
    }

private:
    const std::string& s_;
    size_t i_ = 0;
    int depth_ = 0;

    [[noreturn]] void fail(const std::string& what) const {
        throw ParseError("JSON error at offset " + std::to_string(i_) + ": " + what);
    }

    void space() {
        while (i_ < s_.size() && (s_[i_] == ' ' || s_[i_] == '\t' || s_[i_] == '\n' || s_[i_] == '\r'))
            ++i_;
    }

    bool literal(const char* word) {
        size_t n = std::char_traits<char>::length(word);
        if (s_.compare(i_, n, word) == 0) {
            i_ += n;
            return true;
        }
        return false;
    }

    Value value() {
        space();
        if (i_ >= s_.size())
            fail("unexpected end");
        char c = s_[i_];
        if (c == '{')
            return object();
        if (c == '[')
            return array();
        if (c == '"')
            return Value::string(string());
        if (literal("true"))
            return Value::boolean(true);
        if (literal("false"))
            return Value::boolean(false);
        if (literal("null"))
            return Value();
        if (c == '-' || (c >= '0' && c <= '9'))
            return number();
        fail(std::string("unexpected '") + c + "'");
    }

    Value object() {
        if (++depth_ > 200)
            fail("nested too deeply");
        ++i_;  // {
        Value obj = Value::object();
        space();
        if (i_ < s_.size() && s_[i_] == '}') {
            ++i_;
            --depth_;
            return obj;
        }
        for (;;) {
            space();
            if (i_ >= s_.size() || s_[i_] != '"')
                fail("expected a key");
            std::string key = string();
            space();
            if (i_ >= s_.size() || s_[i_] != ':')
                fail("expected ':'");
            ++i_;
            obj.set(key, value());
            space();
            if (i_ < s_.size() && s_[i_] == ',') {
                ++i_;
                continue;
            }
            if (i_ < s_.size() && s_[i_] == '}') {
                ++i_;
                --depth_;
                return obj;
            }
            fail("expected ',' or '}'");
        }
    }

    Value array() {
        if (++depth_ > 200)
            fail("nested too deeply");
        ++i_;  // [
        Value arr = Value::array();
        space();
        if (i_ < s_.size() && s_[i_] == ']') {
            ++i_;
            --depth_;
            return arr;
        }
        for (;;) {
            arr.push(value());
            space();
            if (i_ < s_.size() && s_[i_] == ',') {
                ++i_;
                continue;
            }
            if (i_ < s_.size() && s_[i_] == ']') {
                ++i_;
                --depth_;
                return arr;
            }
            fail("expected ',' or ']'");
        }
    }

    Value number() {
        size_t start = i_;
        if (s_[i_] == '-')
            ++i_;
        while (i_ < s_.size() && ((s_[i_] >= '0' && s_[i_] <= '9') || s_[i_] == '.' || s_[i_] == 'e'
                                  || s_[i_] == 'E' || s_[i_] == '+' || s_[i_] == '-'))
            ++i_;
        // Always '.' as the decimal point, whatever the program's locale.
        std::istringstream in(s_.substr(start, i_ - start));
        in.imbue(std::locale::classic());
        double d = 0;
        in >> d;
        if (in.fail() || !in.eof())
            fail("bad number");
        return Value::number(d);
    }

    unsigned hex4() {
        if (i_ + 4 > s_.size())
            fail("bad \\u escape");
        unsigned v = 0;
        for (int k = 0; k < 4; ++k) {
            char h = s_[i_++];
            v <<= 4;
            if (h >= '0' && h <= '9') v |= h - '0';
            else if (h >= 'a' && h <= 'f') v |= h - 'a' + 10;
            else if (h >= 'A' && h <= 'F') v |= h - 'A' + 10;
            else fail("bad \\u escape");
        }
        return v;
    }

    static void utf8(std::string& out, unsigned cp) {
        if (cp < 0x80) {
            out += static_cast<char>(cp);
        } else if (cp < 0x800) {
            out += static_cast<char>(0xC0 | (cp >> 6));
            out += static_cast<char>(0x80 | (cp & 0x3F));
        } else if (cp < 0x10000) {
            out += static_cast<char>(0xE0 | (cp >> 12));
            out += static_cast<char>(0x80 | ((cp >> 6) & 0x3F));
            out += static_cast<char>(0x80 | (cp & 0x3F));
        } else {
            out += static_cast<char>(0xF0 | (cp >> 18));
            out += static_cast<char>(0x80 | ((cp >> 12) & 0x3F));
            out += static_cast<char>(0x80 | ((cp >> 6) & 0x3F));
            out += static_cast<char>(0x80 | (cp & 0x3F));
        }
    }

    std::string string() {
        ++i_;  // "
        std::string out;
        for (;;) {
            if (i_ >= s_.size())
                fail("unterminated string");
            char c = s_[i_++];
            if (c == '"')
                return out;
            if (c != '\\') {
                out += c;
                continue;
            }
            if (i_ >= s_.size())
                fail("unterminated string");
            char e = s_[i_++];
            switch (e) {
            case '"': out += '"'; break;
            case '\\': out += '\\'; break;
            case '/': out += '/'; break;
            case 'b': out += '\b'; break;
            case 'f': out += '\f'; break;
            case 'n': out += '\n'; break;
            case 'r': out += '\r'; break;
            case 't': out += '\t'; break;
            case 'u': {
                unsigned cp = hex4();
                if (cp >= 0xD800 && cp < 0xDC00 && i_ + 1 < s_.size() && s_[i_] == '\\' && s_[i_ + 1] == 'u') {
                    i_ += 2;
                    unsigned low = hex4();
                    cp = 0x10000 + ((cp - 0xD800) << 10) + (low - 0xDC00);
                }
                utf8(out, cp);
                break;
            }
            default: fail("bad escape");
            }
        }
    }
};

}  // namespace detail

// Parse a JSON document. Throws ParseError.
inline Value parse(const std::string& text) {
    return detail::Parser(text).document();
}

}  // namespace json
}  // namespace vl

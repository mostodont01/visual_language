// VL runtime: the small library every compiled VL program is built on.
//
// A node is a C++ class derived from vl::Node, with one member per socket
// and setting in its JSON, named after their ids:
//
//     inputs    vl::Input<T>     read with get()
//     outputs   vl::Output<T>    write with set(value)
//     settings  plain members    (assigned before setup())
//
// The generated program is split so that small changes rebuild little:
//   generated/node_<type>.cpp  one per node type: describes the type (how to
//                              create it, its sockets and settings) as a
//                              vl::NodeType. Only this file includes the
//                              node's headers.
//   generated/main.cpp         creates the nodes and connects the wires, by
//                              socket id. Depends only on the graph's shape.
//   <program>.values.json      settings, initial input values and widget
//                              options, read at start-up (next to the
//                              program, or the file in VL_VALUES). Changing a
//                              value needs no compiling at all.
//
// When a node runs: whenever one of its inputs receives a new value, using
// the latest value of every other input, and only once every required input
// has had a value. Exceptions:
//   - optional inputs ("optional": true) never hold a node back: they start
//     with their default and keep it until a value arrives;
//   - non-triggering inputs ("triggers": false) store new values without
//     starting a run;
//   - wires that close a feedback loop don't start a run either; they only
//     update the stored value, so loops can't run forever.
#pragma once

#include <cmath>
#include <cstdint>
#include <deque>
#include <functional>
#include <memory>
#include <string>
#include <type_traits>
#include <typeindex>
#include <vector>

#include "vl/json.hpp"

namespace vl {

class App;
class Node;
struct NodeType;

// The program's clock, in seconds (only differences mean anything). Normally
// real time. In fast mode (environment variable VL_FAST=1, headless only) it
// is simulated time: instead of waiting for the next timer the program jumps
// straight to it, so a simulation runs as fast as the computer can and gives
// the same result every run. Nodes should use this, not their own clock.
// VL_STOP_AFTER=<seconds> ends a headless run after that long on this clock.
double now();

template <typename T> class Output;

// The part of every input the runtime needs to see.
class InputBase {
public:
    // A value has arrived (over a wire, or from the input's field).
    // An optional input's default doesn't count.
    bool hasValue() const { return hasValue_; }
    // A wire is connected to this input.
    bool connected() const { return connected_; }

protected:
    template <typename T> friend class Output;

    bool hasValue_ = false;
    bool connected_ = false;
};

template <typename T>
class Input : public InputBase {
public:
    const T& get() const { return value_; }
    operator const T&() const { return value_; }

    // Called by the runtime (and the generated code for initial values).
    void receive(const T& value) {
        value_ = value;
        hasValue_ = true;
    }

    // Set the starting value of an optional input (doesn't count as a value
    // having arrived).
    void init(const T& value) { value_ = value; }

private:
    T value_{};
};

class Node {
public:
    virtual ~Node() = default;

    // Called once, after settings are assigned and before anything runs.
    virtual void setup() {}
    // Called whenever the node runs (see above).
    virtual void process() {}
    // Draw the node's app widget with Dear ImGui. Only called for nodes with
    // an app widget that is shown; wrap the body in #ifdef VL_GUI.
    virtual void drawWidget() {}

protected:
    // Call from setup(): additionally run process() every `seconds`
    // (for sources such as sensors).
    void runEvery(double seconds);
    // Run process() again soon, e.g. after the user changed a widget.
    void requestProcess();

private:
    friend class App;
    template <typename T> friend class Output;

    bool vlReady() const;

    App* vlApp_ = nullptr;
    const NodeType* vlType_ = nullptr;  // Set for nodes made by App::create().
    std::string vlId_;
    std::string vlTitle_;
    std::vector<const InputBase*> vlInputs_;
    bool vlQueued_ = false;
    double vlInterval_ = 0;
    double vlNextRun_ = 0;
    bool vlHasWidget_ = false;
    bool vlWidgetVisible_ = false;
    std::string vlWidgetTitle_;
};

template <typename T>
class Output {
public:
    // Send a value to every connected input.
    void set(const T& value) {
        for (auto& link : links_) {
            link.input->receive(value);
            if (link.triggers)
                link.node->requestProcess();
        }
    }

    Output& operator=(const T& value) {
        set(value);
        return *this;
    }

    // Used by the generated code. Feedback wires have triggers = false.
    void connect(Input<T>& input, Node& node, bool triggers) {
        input.connected_ = true;
        links_.push_back({&input, &node, triggers});
    }

private:
    struct Link {
        Input<T>* input;
        Node* node;
        bool triggers;
    };
    std::vector<Link> links_;
};

// -- Node types ---------------------------------------------------------------
// A node type described for the runtime, so nodes can be created and wired by
// id without the code that does it knowing the node's class. Written by the
// generated generated/node_<type>.cpp files.

// A value from the values file as T: numbers, bool and std::string directly,
// other types from a string if they can be made from one; null gives T{}.
template <typename T>
T fromValue(const json::Value& v) {
    if (v.isNull())
        return T{};
    if constexpr (std::is_same_v<T, bool>) {
        return v.asBool();
    } else if constexpr (std::is_integral_v<T>) {
        return static_cast<T>(std::llround(v.asNumber()));
    } else if constexpr (std::is_floating_point_v<T>) {
        return static_cast<T>(v.asNumber());
    } else if constexpr (std::is_constructible_v<T, std::string>) {
        return T(v.asString());
    } else {
        return T{};
    }
}

struct InputPort {
    std::string id;
    std::string type;           // VL type name (for messages)
    std::type_index cppType;    // must match the output it's connected to
    bool optional;
    std::function<InputBase&(Node&)> get;
    // Give the input its starting value: receive (counts as a value) or init.
    std::function<void(Node&, const json::Value&, bool receive)> start;
};

struct OutputPort {
    std::string id;
    std::string type;
    std::type_index cppType;
    // Connect this output of `from` to `input` (of the same C++ type) of `to`.
    std::function<void(Node& from, Node& to, InputBase& input, bool triggers)> connect;
};

struct SettingPort {
    std::string id;
    std::function<void(Node&, const json::Value&)> set;
};

struct NodeType {
    std::string id;
    std::string title;
    std::function<std::unique_ptr<Node>()> create;
    std::vector<InputPort> inputs;
    std::vector<OutputPort> outputs;
    std::vector<SettingPort> settings;
    bool hasWidget = false;
};

template <typename N, typename T>
InputPort inputPort(const char* id, const char* type, bool optional, Input<T> N::*member) {
    return {id, type, std::type_index(typeid(T)), optional,
            [member](Node& n) -> InputBase& { return static_cast<N&>(n).*member; },
            [member](Node& n, const json::Value& v, bool receive) {
                Input<T>& input = static_cast<N&>(n).*member;
                if (receive)
                    input.receive(fromValue<T>(v));
                else
                    input.init(fromValue<T>(v));
            }};
}

template <typename N, typename T>
OutputPort outputPort(const char* id, const char* type, Output<T> N::*member) {
    return {id, type, std::type_index(typeid(T)),
            [member](Node& from, Node& to, InputBase& input, bool triggers) {
                (static_cast<N&>(from).*member).connect(static_cast<Input<T>&>(input), to, triggers);
            }};
}

template <typename N, typename T>
SettingPort settingPort(const char* id, T N::*member) {
    return {id, [member](Node& n, const json::Value& v) { static_cast<N&>(n).*member = fromValue<T>(v); }};
}

class App {
public:
    // gui: open a window for app widgets (only built with VL_GUI). The name
    // and fullscreen flag come from the values file (loadValues()).
    explicit App(bool gui);
    App(std::string name, bool fullscreen, bool gui);

    // Create a node of a described type. Its required inputs are watched.
    Node& create(const NodeType& type, const std::string& id);
    // Wire an output to an input by socket id. Problems are reported by run().
    void connect(Node& from, const std::string& output, Node& to, const std::string& input, bool triggers);
    // Read the values file and apply it to the nodes made by create(): the
    // file in the environment variable VL_VALUES, else <program>.values.json
    // next to the program. Returns false (after printing why) if it can't.
    bool loadValues(int argc, char** argv);
    bool loadValuesFrom(const std::string& path);

    template <typename N>
    N& add(const std::string& id, const std::string& title) {
        auto node = std::make_unique<N>();
        N& ref = *node;
        ref.vlApp_ = this;
        ref.vlId_ = id;
        ref.vlTitle_ = title;
        nodes_.push_back(std::move(node));
        return ref;
    }

    // Inputs the node needs a value on before it can run (not optional ones).
    void watch(Node& node, const InputBase& input);
    void setWidget(Node& node, bool visible, const std::string& title);

    int run();

private:
    friend class Node;

    void schedule(Node& node);
    void runTimers();
    void processQueue();
    double nextTimer() const;
    int runHeadless();
#ifdef VL_GUI
    int runGui();
    void drawWidgets(float width, float height);
#endif

    void error(const std::string& message);

    std::string name_;
    bool fullscreen_;
    bool gui_;
    int errors_ = 0;
    std::vector<std::unique_ptr<Node>> nodes_;
    std::deque<Node*> queue_;
};

}  // namespace vl

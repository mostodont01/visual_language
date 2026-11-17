// VL runtime: the small library every compiled VL program is built on.
//
// A node is a C++ class derived from vl::Node, with one member per socket
// and setting in its JSON, named after their ids:
//
//     inputs    vl::Input<T>     read with get()
//     outputs   vl::Output<T>    write with set(value)
//     settings  plain members    (assigned before setup())
//
// The generated main() creates the nodes, assigns their values, connects
// outputs to inputs and runs vl::App.
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

#include <cstdint>
#include <deque>
#include <memory>
#include <string>
#include <vector>

namespace vl {

class App;
class Node;

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

class App {
public:
    // gui: open a window for app widgets (only built with VL_GUI).
    App(std::string name, bool fullscreen, bool gui);

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

    std::string name_;
    bool fullscreen_;
    bool gui_;
    std::vector<std::unique_ptr<Node>> nodes_;
    std::deque<Node*> queue_;
};

}  // namespace vl

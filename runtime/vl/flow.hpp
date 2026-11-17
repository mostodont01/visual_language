// Flows: start-up and event sequences that run in execution order (like
// Blender's or Unreal's exec wires), next to the dataflow "main tree".
// Included by vl/runtime.hpp.
//
// A flow node has exec sockets ("type": "exec" in its JSON). Its C++ class
// derives from vl::FlowNode. Exec sockets have no C++ members: exec outputs
// are numbered in JSON order (0, 1, ...).
//
//   start()    execution arrived at the node
//   update()   called right after start() and then whenever one of the node's
//              inputs changes, its timer fires (runEvery / wakeAt) or it
//              calls requestProcess(). Return Running to stay on this node,
//              or the number of the exec output to continue on. Never block:
//              everything else keeps running in the meantime.
//
// Phases of a program:
//   start-up   the flow from On Start runs; the main tree waits. It ends at
//              Start Main. Graphs without On Start skip this phase.
//   main       the main tree (every data node) runs.
//   event      an On Event fired (rising edge of its trigger, in any phase):
//              the main tree (or the start-up flow, or a lower-priority event
//              flow) is stopped and the event's flow runs. It ends at Resume
//              Main, Restart or Stop Program.
//
// Which data nodes run when: in the main phase all of them; during a flow
// only those the flow needs (upstream of its nodes' data inputs, plus
// downstream of their data outputs). The nodes feeding On Event triggers
// always run. The compiler works this out (App::setGroups).
#pragma once

#include <climits>
#include <cstdio>

#include "vl/runtime.hpp"

namespace vl {

class FlowNode : public Node {
public:
    // update() results besides exec output numbers.
    static constexpr int Running = -1;     // stay on this node
    static constexpr int EndFlow = -2;     // end this flow here (nothing else happens)
    static constexpr int StartMain = -3;   // start-up flow done: start the main tree
    static constexpr int ResumeMain = -4;  // event flow done: back to what was interrupted
    static constexpr int Restart = -5;     // reset() every node, run the start-up flow again
    static constexpr int StopProgram = -6; // stop() every node and end the program

    // Execution arrived at this node.
    virtual void start() {}
    // See above. The default continues on exec output 0 at once.
    virtual int update() { return 0; }

    // Entry nodes (no exec input): On Start is the start-up flow's entry.
    virtual bool isStartEntry() const { return false; }

protected:
    // Entry nodes: start this node's flow (e.g. On Event on a rising edge).
    // Higher priority interrupts lower; the start-up flow counts as lowest.
    void fire(int priority);

private:
    friend class App;

    std::vector<Node*> vlExec_;   // target of each exec output (null: not connected)
    bool vlEntry_ = false;
    int vlGroup_ = 0;             // entries: the flow's group bit
};

inline void FlowNode::fire(int priority) {
    if (vlApp_)
        vlApp_->requestFlow(*this, priority);
}

// -- Built-in flow nodes ------------------------------------------------------

// Start of the start-up flow. The main tree starts at Start Main.
class OnStart : public FlowNode {
public:
    bool isStartEntry() const override { return true; }
};

// Starts its flow on the rising edge of `trigger`, in any phase.
class OnEvent : public FlowNode {
public:
    Input<bool> trigger;
    int32_t priority = 0;

    void process() override {
        bool now = trigger.get();
        if (now && !last_)
            fire(priority);
        last_ = now;
    }
    void reset() override { last_ = false; }

private:
    bool last_ = false;
};

class StartMainNode : public FlowNode {
public:
    int update() override { return StartMain; }
};

class ResumeMainNode : public FlowNode {
public:
    int update() override { return ResumeMain; }
};

class RestartNode : public FlowNode {
public:
    int update() override { return Restart; }
};

class StopProgramNode : public FlowNode {
public:
    int update() override { return StopProgram; }
};

// Waits `seconds` (on vl::now(), so fast mode skips it).
class Wait : public FlowNode {
public:
    Input<float> seconds;

    void start() override {
        until_ = now() + seconds.get();
        wakeAt(until_);
    }
    int update() override { return now() >= until_ ? 0 : Running; }

private:
    double until_ = 0;
};

// Waits until `condition` is true (continues at once if it already is).
class WaitUntil : public FlowNode {
public:
    Input<bool> condition;

    int update() override { return condition.get() ? 0 : Running; }
};

// Continues on "true" (0) or "false" (1).
class Branch : public FlowNode {
public:
    Input<bool> condition;

    int update() override { return condition.get() ? 0 : 1; }
};

// Prints a message.
class Log : public FlowNode {
public:
    Input<std::string> message;

    int update() override {
        std::printf("%s\n", message.get().c_str());
        return 0;
    }
};

}  // namespace vl

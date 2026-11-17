#include "vl/runtime.hpp"

#include <algorithm>
#include <chrono>
#include <climits>
#include <cmath>
#include <csignal>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <sstream>
#include <string>
#include <thread>

#ifdef _WIN32
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#else
#include <unistd.h>
#endif

#ifdef VL_GUI
#define SDL_MAIN_HANDLED  // main() is ours (generated/main.cpp), not SDL's.
#include <SDL.h>
#include "imgui.h"
#include "imgui_impl_sdl2.h"
#include "imgui_impl_sdlrenderer2.h"
#endif

namespace vl {

namespace {

double realNow() {
    using namespace std::chrono;
    return duration<double>(steady_clock::now().time_since_epoch()).count();
}

// Fast mode's simulated clock; negative = real time.
double fastClock = -1;

bool envFlag(const char* name) {
    const char* value = std::getenv(name);
    return value && *value && std::string(value) != "0";
}

// The running program's file, or argv[0] if the system can't tell.
std::string programPath(const char* argv0) {
#ifdef _WIN32
    char buffer[MAX_PATH * 4];
    DWORD n = GetModuleFileNameA(nullptr, buffer, sizeof buffer);
    if (n > 0 && n < sizeof buffer)
        return std::string(buffer, n);
#else
    char buffer[4096];
    ssize_t n = readlink("/proc/self/exe", buffer, sizeof buffer);
    if (n > 0 && n < static_cast<ssize_t>(sizeof buffer))
        return std::string(buffer, static_cast<size_t>(n));
#endif
    return argv0 ? argv0 : "";
}

}  // namespace

double now() {
    return fastClock >= 0 ? fastClock : realNow();
}

// -- Node ---------------------------------------------------------------------

void Node::runEvery(double seconds) {
    vlInterval_ = seconds > 0 ? seconds : 0;
}

void Node::wakeAt(double time) {
    vlWakeAt_ = time > 0 ? time : 1e-9;
}

void Node::requestProcess() {
    if (vlApp_)
        vlApp_->schedule(*this);
}

bool Node::vlReady() const {
    for (const InputBase* input : vlInputs_) {
        if (!input->hasValue())
            return false;
    }
    return true;
}

// -- App ----------------------------------------------------------------------

App::App(bool gui) : name_("VL"), fullscreen_(true), gui_(gui) {}

App::App(std::string name, bool fullscreen, bool gui)
    : name_(std::move(name)), fullscreen_(fullscreen), gui_(gui) {}

void App::error(const std::string& message) {
    std::fprintf(stderr, "vl: %s\n", message.c_str());
    ++errors_;
}

Node& App::create(const NodeType& type, const std::string& id) {
    std::unique_ptr<Node> node = type.create();
    Node& ref = *node;
    ref.vlApp_ = this;
    ref.vlType_ = &type;
    ref.vlId_ = id;
    ref.vlTitle_ = type.title;
    ref.vlFlow_ = dynamic_cast<FlowNode*>(&ref);
    for (const InputPort& port : type.inputs) {
        if (!port.optional)
            watch(ref, port.get(ref));
    }
    if (type.hasWidget)
        setWidget(ref, true, type.title);
    nodes_.push_back(std::move(node));
    return ref;
}

void App::connect(Node& from, const std::string& output, Node& to, const std::string& input, bool triggers) {
    if (!from.vlType_ || !to.vlType_) {
        error("connect() needs nodes made by create()");
        return;
    }
    const OutputPort* out = nullptr;
    for (const OutputPort& port : from.vlType_->outputs)
        if (port.id == output)
            out = &port;
    const InputPort* in = nullptr;
    for (const InputPort& port : to.vlType_->inputs)
        if (port.id == input)
            in = &port;
    if (!out || !in) {
        error("no socket " + (out ? to.vlId_ + "." + input : from.vlId_ + "." + output)
              + " (the program is older than its node code? compile again)");
        return;
    }
    if (out->cppType != in->cppType) {
        error("can't connect " + from.vlId_ + "." + output + " (" + out->type + ") to " + to.vlId_ + "."
              + input + " (" + in->type + "): different C++ types");
        return;
    }
    out->connect(from, to, in->get(to), triggers);
}

bool App::loadValues(int argc, char** argv) {
    const char* override = std::getenv("VL_VALUES");
    if (override && *override)
        return loadValuesFrom(override);
    std::string path = programPath(argc > 0 ? argv[0] : nullptr);
    if (path.size() > 4 && (path.compare(path.size() - 4, 4, ".exe") == 0
                            || path.compare(path.size() - 4, 4, ".EXE") == 0))
        path.resize(path.size() - 4);
    return loadValuesFrom(path + ".values.json");
}

bool App::loadValuesFrom(const std::string& path) {
    std::ifstream file(path, std::ios::binary);
    if (!file) {
        std::fprintf(stderr, "vl: can't read the values file %s. It is written by VL next to the "
                             "program; copy it along with the program (or set VL_VALUES).\n", path.c_str());
        return false;
    }
    std::stringstream text;
    text << file.rdbuf();
    json::Value root;
    try {
        root = json::parse(text.str());
    } catch (const json::ParseError& e) {
        std::fprintf(stderr, "vl: %s: %s\n", path.c_str(), e.what());
        return false;
    }

    const json::Value& app = root["app"];
    if (app["name"].isString())
        name_ = app["name"].asString();
    if (app["fullscreen"].isBool())
        fullscreen_ = app["fullscreen"].asBool();

    const json::Value& entries = root["nodes"];
    for (auto& node : nodes_) {
        const NodeType* type = node->vlType_;
        const json::Value& entry = entries[node->vlId_];
        if (!type || !entry.isObject())
            continue;
        for (const auto& [key, value] : entry["settings"].members()) {
            bool found = false;
            for (const SettingPort& port : type->settings) {
                if (port.id == key) {
                    port.set(*node, value);
                    found = true;
                }
            }
            if (!found)
                std::fprintf(stderr, "vl: %s: %s has no setting '%s' (ignored)\n", path.c_str(),
                             node->vlId_.c_str(), key.c_str());
        }
        for (const auto& [key, start] : entry["inputs"].members()) {
            bool found = false;
            for (const InputPort& port : type->inputs) {
                if (port.id != key)
                    continue;
                found = true;
                if (start.has("receive"))
                    port.start(*node, start["receive"], true);
                else if (start.has("init"))
                    port.start(*node, start["init"], false);
            }
            if (!found)
                std::fprintf(stderr, "vl: %s: %s has no input '%s' (ignored)\n", path.c_str(),
                             node->vlId_.c_str(), key.c_str());
        }
        const json::Value& widget = entry["widget"];
        if (widget.isObject() && node->vlHasWidget_) {
            if (widget["visible"].isBool())
                node->vlWidgetVisible_ = widget["visible"].asBool();
            if (widget["title"].isString())
                node->vlWidgetTitle_ = widget["title"].asString();
        }
    }
    return true;
}

void App::watch(Node& node, const InputBase& input) {
    node.vlInputs_.push_back(&input);
}

void App::setWidget(Node& node, bool visible, const std::string& title) {
    node.vlHasWidget_ = true;
    node.vlWidgetVisible_ = visible;
    node.vlWidgetTitle_ = title;
}

void App::schedule(Node& node) {
    if (!node.vlQueued_) {
        node.vlQueued_ = true;
        queue_.push_back(&node);
    }
}

void App::runTimers() {
    double now = vl::now();
    for (auto& node : nodes_) {
        if (!runnable(*node))
            continue;
        if (node->vlInterval_ > 0 && now >= node->vlNextRun_) {
            node->vlNextRun_ += node->vlInterval_;
            if (node->vlNextRun_ < now)  // Fell behind: don't try to catch up.
                node->vlNextRun_ = now + node->vlInterval_;
            schedule(*node);
        }
        if (node->vlWakeAt_ > 0 && now >= node->vlWakeAt_) {
            node->vlWakeAt_ = 0;
            schedule(*node);
        }
    }
}

void App::processQueue() {
    // Feedback wires never schedule a node, so this always ends; the limit is
    // only a safety net.
    for (int i = 0; i < 100000 && !queue_.empty() && !quit_; ++i) {
        Node* node = queue_.front();
        queue_.pop_front();
        node->vlQueued_ = false;

        FlowNode* flow = node->vlFlow_;
        if (flow && !flow->vlEntry_) {
            // Flow nodes only react while their flow is at them.
            if (flow == flowAt_)
                step(flow->update());
            continue;
        }
        if (!(node->vlGroups_ & active_)) {
            node->vlPending_ = true;  // Runs once its group is active again.
            continue;
        }
        if (node->vlReady())
            node->process();
        if (requested_)
            handleFlowRequest();
    }
    if (flowStarting_ && !quit_ && flowAt_) {
        flowStarting_ = false;
        flowAt_->start();
        step(flowAt_->update());
    } else if (stepPending_ && !quit_) {
        stepPending_ = false;
        step(pendingResult_);
    }
}

double App::nextTimer() const {
    double next = INFINITY;
    for (const auto& node : nodes_) {
        if (!runnable(*node))
            continue;
        if (node->vlInterval_ > 0)
            next = std::min(next, node->vlNextRun_);
        if (node->vlWakeAt_ > 0)
            next = std::min(next, node->vlWakeAt_);
    }
    return next;
}

// -- Flows ----------------------------------------------------------------------

void App::connectExec(Node& from, int output, Node& to) {
    from.vlFlow_ = dynamic_cast<FlowNode*>(&from);
    to.vlFlow_ = dynamic_cast<FlowNode*>(&to);
    if (!from.vlFlow_ || !to.vlFlow_ || output < 0) {
        error("exec wires connect flow nodes (" + from.vlId_ + " -> " + to.vlId_ + ")");
        return;
    }
    auto& exec = from.vlFlow_->vlExec_;
    if (exec.size() <= static_cast<size_t>(output))
        exec.resize(output + 1, nullptr);
    exec[output] = &to;
}

void App::addFlowEntry(Node& entry, int group) {
    entry.vlFlow_ = dynamic_cast<FlowNode*>(&entry);
    if (!entry.vlFlow_ || group < 2 || group > 63) {
        error("bad flow entry " + entry.vlId_);
        return;
    }
    entry.vlFlow_->vlEntry_ = true;
    entry.vlFlow_->vlGroup_ = group;
    entry.vlGroups_ = GroupAlways;
}

void App::setGroups(Node& node, uint64_t groups) {
    node.vlGroups_ = groups;
}

bool App::runnable(const Node& node) const {
    if (node.vlFlow_ && !node.vlFlow_->vlEntry_)
        return node.vlFlow_ == flowAt_;
    return (node.vlGroups_ & active_) != 0;
}

void App::setActive(uint64_t groups) {
    uint64_t old = active_;
    active_ = groups;
    double now = vl::now();
    for (auto& node : nodes_) {
        if (node->vlFlow_ && !node->vlFlow_->vlEntry_)
            continue;
        bool was = (node->vlGroups_ & old) != 0;
        bool is = (node->vlGroups_ & groups) != 0;
        if (was && !is) {
            node->stop();
        } else if (!was && is) {
            // Back in action: timers start over, and anything it missed runs now.
            if (node->vlInterval_ > 0) {
                node->vlNextRun_ = now + node->vlInterval_;
                node->vlPending_ = true;
            }
            if (node->vlPending_) {
                node->vlPending_ = false;
                schedule(*node);
            }
        }
    }
}

void App::requestFlow(FlowNode& entry, int priority) {
    if (!requested_ || priority > requestedPriority_) {
        requested_ = &entry;
        requestedPriority_ = priority;
    }
}

void App::handleFlowRequest() {
    FlowNode* entry = requested_;
    requested_ = nullptr;
    if (entry && !quit_)
        startFlow(*entry, requestedPriority_);
}

void App::startFlow(FlowNode& entry, int priority) {
    // A running flow only gives way to a higher priority (the start-up flow
    // has the lowest).
    if (flowEntry_ && priority <= flowPriority_)
        return;
    if (flowAt_)
        flowAt_->stop();
    flowEntry_ = &entry;
    flowPriority_ = priority;
    flowAt_ = &entry;
    stepPending_ = false;
    flowStarting_ = false;
    setActive(GroupAlways | (uint64_t(1) << entry.vlGroup_));
    // The flow's first step waits until the data nodes it needs have run
    // (end of processQueue()), so it sees their current values.
    flowStarting_ = true;
}

void App::step(int result) {
    // Follow the flow until a node waits. Many steps without waiting (a loop
    // in the flow) continue on the next pass, so the program stays responsive.
    for (int guard = 0; guard < 10000; ++guard) {
        if (!flowAt_ || quit_ || result == FlowNode::Running)
            return;
        if (result >= 0) {
            const auto& exec = flowAt_->vlExec_;
            Node* next = static_cast<size_t>(result) < exec.size() ? exec[result] : nullptr;
            if (!next) {
                endFlow();  // An exec output without a wire: the flow ends here.
                return;
            }
            flowAt_ = next->vlFlow_;
            flowAt_->vlWakeAt_ = 0;
            flowAt_->start();
            result = flowAt_->update();
            continue;
        }
        switch (result) {
        case FlowNode::StartMain: startMain(); return;
        case FlowNode::ResumeMain: resumeMain(); return;
        case FlowNode::Restart: restart(); return;
        case FlowNode::StopProgram: quit(0); return;
        default: endFlow(); return;
        }
    }
    stepPending_ = true;
    pendingResult_ = result;
}

void App::endFlow() {
    // Nothing runs but what watches the events.
    flowEntry_ = flowAt_ = nullptr;
    setActive(GroupAlways);
}

void App::startMain() {
    flowEntry_ = flowAt_ = nullptr;
    mainStarted_ = true;
    setActive(GroupAlways | GroupMain);
}

void App::resumeMain() {
    // Back to the main tree if it was running; if the start-up flow was
    // interrupted, it starts over.
    if (mainStarted_ || !startEntry_)
        startMain();
    else
        runStartUp();
}

void App::restart() {
    flowEntry_ = flowAt_ = nullptr;
    setActive(GroupAlways);
    for (auto& node : nodes_)
        node->reset();
    mainStarted_ = false;
    if (startEntry_)
        runStartUp();
    else
        startMain();
}

void App::runStartUp() {
    flowEntry_ = flowAt_ = nullptr;
    startFlow(*startEntry_, INT_MIN);
}

void App::quit(int code) {
    quit_ = true;
    exitCode_ = code;
}

void App::stopAll() {
    for (auto& node : nodes_)
        node->stop();
}

// -- Running ----------------------------------------------------------------------

namespace {
volatile std::sig_atomic_t signalled = 0;
extern "C" void onSignal(int) { signalled = 1; }
}  // namespace

int App::run() {
    if (errors_ > 0)
        return 1;

    // Show prints from nodes right away, also when piped into a log.
#ifdef _WIN32
    std::setvbuf(stdout, nullptr, _IONBF, 0);  // Windows has no line buffering.
#else
    std::setvbuf(stdout, nullptr, _IOLBF, 0);
#endif

    // Ctrl+C and SIGTERM end the program properly: every node's stop() runs.
    std::signal(SIGINT, onSignal);
    std::signal(SIGTERM, onSignal);

    for (auto& node : nodes_) {
        node->vlFlow_ = dynamic_cast<FlowNode*>(node.get());
        if (node->vlFlow_ && node->vlFlow_->vlEntry_ && node->vlFlow_->isStartEntry() && !startEntry_)
            startEntry_ = node->vlFlow_;
    }
    // Fast mode: simulated time, from an arbitrary start (not 0, which nodes
    // may use for "not yet"). Started before setup(), so nodes can use the
    // clock there.
    const bool fast = envFlag("VL_FAST");
    if (fast)
        fastClock = 1000.0;

    for (auto& node : nodes_)
        node->setup();

    // Every node gets one chance to run at the start (sources, constants...).
    // Nodes whose group isn't active get it once it is.
    double now = vl::now();
    for (auto& node : nodes_) {
        if (node->vlInterval_ > 0)
            node->vlNextRun_ = now + node->vlInterval_;
        schedule(*node);
    }

    // With an On Start, the start-up flow runs first and the main tree waits.
    if (startEntry_) {
        active_ = GroupAlways;
        runStartUp();
    } else {
        active_ = GroupAlways | GroupMain;
        mainStarted_ = true;
    }

    int code = 0;
#ifdef VL_GUI
    if (gui_ && !fast)
        code = runGui();
    else
#endif
        code = runHeadless();
    stopAll();
    return quit_ ? exitCode_ : code;
}

int App::runHeadless() {
    const char* stopAfter = std::getenv("VL_STOP_AFTER");
    const double stopAt = stopAfter && *stopAfter ? vl::now() + std::atof(stopAfter) : INFINITY;
    for (;;) {
        if (signalled || quit_)
            return 0;
        processQueue();
        runTimers();
        if (!queue_.empty() || stepPending_ || flowStarting_)
            continue;
        if (quit_)
            return 0;

        double next = nextTimer();
        if (std::isinf(next))
            return 0;  // Nothing can happen any more.
        if (next >= stopAt)
            return 0;
        if (fastClock >= 0) {
            fastClock = std::max(fastClock, next);  // Jump straight there.
            continue;
        }
        // Sleep until the next timer, waking now and then to notice Ctrl+C.
        double wait = std::min(next - realNow(), 0.1);
        if (wait > 0)
            std::this_thread::sleep_for(std::chrono::duration<double>(wait));
    }
}

#ifdef VL_GUI

int App::runGui() {
    SDL_SetMainReady();
    if (SDL_Init(SDL_INIT_VIDEO | SDL_INIT_TIMER) != 0) {
        std::fprintf(stderr, "vl: no display (%s), running without widgets\n", SDL_GetError());
        return runHeadless();
    }

    Uint32 flags = SDL_WINDOW_RESIZABLE | SDL_WINDOW_ALLOW_HIGHDPI;
    if (fullscreen_)
        flags |= SDL_WINDOW_FULLSCREEN_DESKTOP;
    SDL_Window* window = SDL_CreateWindow(name_.c_str(), SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED,
                                          1280, 720, flags);
    SDL_Renderer* renderer = SDL_CreateRenderer(window, -1, SDL_RENDERER_PRESENTVSYNC | SDL_RENDERER_ACCELERATED);
    if (!window || !renderer) {
        std::fprintf(stderr, "vl: could not open a window (%s)\n", SDL_GetError());
        SDL_Quit();
        return runHeadless();
    }

    IMGUI_CHECKVERSION();
    ImGui::CreateContext();
    ImGuiIO& io = ImGui::GetIO();
    io.IniFilename = nullptr;  // Layout is automatic; nothing to remember.
    ImGui::StyleColorsDark();
    ImGui_ImplSDL2_InitForSDLRenderer(window, renderer);
    ImGui_ImplSDLRenderer2_Init(renderer);

    bool running = true;
    while (running && !quit_) {
        if (signalled)
            running = false;
        SDL_Event event;
        while (SDL_PollEvent(&event)) {
            ImGui_ImplSDL2_ProcessEvent(&event);
            if (event.type == SDL_QUIT)
                running = false;
            if (event.type == SDL_KEYDOWN && event.key.keysym.sym == SDLK_ESCAPE)
                running = false;
        }

        runTimers();
        processQueue();

        ImGui_ImplSDLRenderer2_NewFrame();
        ImGui_ImplSDL2_NewFrame();
        ImGui::NewFrame();
        drawWidgets(io.DisplaySize.x, io.DisplaySize.y);
        ImGui::Render();

        SDL_RenderSetScale(renderer, io.DisplayFramebufferScale.x, io.DisplayFramebufferScale.y);
        SDL_SetRenderDrawColor(renderer, 23, 25, 29, 255);
        SDL_RenderClear(renderer);
        ImGui_ImplSDLRenderer2_RenderDrawData(ImGui::GetDrawData(), renderer);
        SDL_RenderPresent(renderer);

        processQueue();  // Values changed by widgets.
    }

    ImGui_ImplSDLRenderer2_Shutdown();
    ImGui_ImplSDL2_Shutdown();
    ImGui::DestroyContext();
    SDL_DestroyRenderer(renderer);
    SDL_DestroyWindow(window);
    SDL_Quit();
    return 0;
}

// Arrange every shown widget in a grid that fills the window. The column
// count is chosen so cells are as close to 16:10 as possible, and all
// widgets share one text size, scaled to the cell size.
void App::drawWidgets(float width, float height) {
    std::vector<Node*> shown;
    for (auto& node : nodes_) {
        if (node->vlHasWidget_ && node->vlWidgetVisible_)
            shown.push_back(node.get());
    }

    if (shown.empty()) {
        const char* text = "No widgets to show.";
        ImVec2 size = ImGui::CalcTextSize(text);
        ImGui::SetNextWindowPos(ImVec2((width - size.x) / 2, (height - size.y) / 2));
        ImGui::Begin("##empty", nullptr, ImGuiWindowFlags_NoDecoration | ImGuiWindowFlags_NoBackground);
        ImGui::TextDisabled("%s", text);
        ImGui::End();
        return;
    }

    const int count = static_cast<int>(shown.size());
    const float margin = 8;
    int columns = 1;
    double bestScore = INFINITY;
    for (int c = 1; c <= count; ++c) {
        int rows = (count + c - 1) / c;
        double aspect = (width / c) / (height / rows);
        double score = std::fabs(std::log(aspect / 1.6));
        if (score < bestScore) {
            bestScore = score;
            columns = c;
        }
    }
    const int rows = (count + columns - 1) / columns;
    const float cellWidth = (width - margin * (columns + 1)) / columns;
    const float cellHeight = (height - margin * (rows + 1)) / rows;

    ImGui::GetIO().FontGlobalScale = std::clamp(std::min(cellWidth / 320.0f, cellHeight / 200.0f), 1.0f, 4.0f);

    const ImGuiWindowFlags flags = ImGuiWindowFlags_NoMove | ImGuiWindowFlags_NoResize
        | ImGuiWindowFlags_NoCollapse | ImGuiWindowFlags_NoSavedSettings;
    for (int i = 0; i < count; ++i) {
        Node* node = shown[i];
        int row = i / columns;
        int column = i % columns;
        ImGui::SetNextWindowPos(ImVec2(margin + column * (cellWidth + margin), margin + row * (cellHeight + margin)));
        ImGui::SetNextWindowSize(ImVec2(cellWidth, cellHeight));
        std::string title = node->vlWidgetTitle_ + "##" + node->vlId_;
        ImGui::Begin(title.c_str(), nullptr, flags);
        node->drawWidget();
        ImGui::End();
    }
}

#endif  // VL_GUI

}  // namespace vl

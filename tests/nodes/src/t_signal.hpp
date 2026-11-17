#pragma once
#include "vl/runtime.hpp"

// Uses wakeAt(), so it only runs when it changes.
class TSignal : public vl::Node {
public:
    float on_at = 1;
    float off_at = -1;
    vl::Output<bool> high;
    vl::Output<bool> low;

    void setup() override { start_ = vl::now(); }
    void process() override {
        double t = vl::now() - start_ + 1e-9;
        bool on = t >= on_at && !(off_at >= 0 && t >= off_at);
        if (!sent_ || on != last_) {
            high.set(on);
            low.set(!on);
            sent_ = true;
            last_ = on;
        }
        if (t < on_at)
            wakeAt(start_ + on_at);
        else if (off_at >= 0 && t < off_at)
            wakeAt(start_ + off_at);
    }

private:
    double start_ = 0;
    bool sent_ = false;
    bool last_ = false;
};

#pragma once
#include "vl/runtime.hpp"

class TTick : public vl::Node {
public:
    int32_t count = 3;
    int32_t start = 1;
    int32_t skip = 0;
    float interval = 1;
    vl::Output<int32_t> value;

    void setup() override { runEvery(interval); }
    void process() override {
        if (skip > 0) {
            --skip;
            return;
        }
        if (sent_ < count)
            value.set(start + sent_++);
    }

private:
    int32_t sent_ = 0;
};

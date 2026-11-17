#pragma once
#include <cstdio>
#include "vl/runtime.hpp"

class TInputs : public vl::Node {
public:
    vl::Input<int32_t> a, b, c, d, e;
    vl::Output<int32_t> sum;

    void process() override {
        std::printf("in a=%d b=%d c=%d d=%d e=%d b.connected=%d b.has=%d c.connected=%d\n",
                    a.get(), b.get(), c.get(), d.get(), e.get(),
                    b.connected(), b.hasValue(), c.connected());
        sum.set(a.get() + b.get() + c.get() + d.get() + e.get());
    }
};

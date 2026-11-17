#pragma once
#include "vl/runtime.hpp"

class TAny : public vl::Node {
public:
    vl::Input<bool> a, b, c;
    vl::Output<bool> any, none;

    void process() override {
        bool v = a.get() || b.get() || c.get();
        any.set(v);
        none.set(!v);
    }
};

#pragma once
#include <cstdio>
#include <string>
#include "vl/runtime.hpp"

class TPrint : public vl::Node {
public:
    std::string label;
    vl::Input<int32_t> value;

    void process() override { std::printf("%s %d\n", label.c_str(), value.get()); }
};

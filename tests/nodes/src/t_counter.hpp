#pragma once
#include <cstdio>
#include <string>
#include "vl/runtime.hpp"

class TCounter : public vl::Node {
public:
    std::string label;
    float interval = 1;
    vl::Output<int32_t> count;

    void setup() override {
        start_ = vl::now();
        runEvery(interval);
    }
    void process() override {
        ++n_;
        std::printf("%s %d t=%.2f\n", label.c_str(), n_, vl::now() - start_);
        count.set(n_);
    }
    void stop() override { std::printf("%s stop t=%.2f\n", label.c_str(), vl::now() - start_); }
    void reset() override {
        n_ = 0;
        std::printf("%s reset\n", label.c_str());
    }

private:
    double start_ = 0;
    int32_t n_ = 0;
};

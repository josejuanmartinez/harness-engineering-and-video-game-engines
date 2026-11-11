/*
  REVIEW 11: lambdas and std::function
  Level 3 | Time: 15 min
  Prepares you for: ../06_events.cpp

  WHAT IT IS
  A lambda is an anonymous function that can capture variables from its surroundings.
  Inside it's an object with operator(), and the captures are its members.
  std::function holds anything callable with a given signature. It's what
  callbacks and event systems use.

  WHAT THE TESTS CHECK
  - count_greater: a lambda that captures threshold, passed to an STL algorithm.
  - apply_to_all: take a std::function and call it.
  - make_counter: a lambda with its own state. It captures start by copy and mutable
    lets it modify it. Each counter is independent (first and second don't
    step on each other).
  - sort_by_abs: a lambda as a custom comparator.

  REMEMBER
    auto add = [](int a, int b) { return a + b; };
    [x]   captures x by copy
    [&x]  captures x by reference
    [=]   captures by copy whatever is used
    [&]   captures by reference whatever is used
    [this]  captures the this pointer
    mutable lets you modify the captured copies

    std::function<int(int)> f = ...;   // holds anything callable

  THINK
  - What happens if you return a lambda that captured a local variable by reference?
  - What's the risk of storing a callback that captures this?
*/
#include <algorithm>
#include <cassert>
#include <cstdlib>
#include <functional>
#include <iostream>
#include <vector>

// How many elements exceed threshold. Use std::count_if and a capture.
int count_greater(const std::vector<int>& values, int threshold) {
    return std::count_if(values.begin(), values.end(), [threshold](int value) { return value > threshold;});
}

// Replaces each element with fn(element).
void apply_to_all(std::vector<int>& values, const std::function<int(int)>& fn) {
    std::transform(values.begin(), values.end(), values.begin(), fn);
}

// Returns a counter: each call returns start, start + 1, start + 2...
std::function<int()> make_counter(int start) {
    return [start]() mutable { return start++; };
}

// Sorts by absolute value, from smallest to largest.
void sort_by_abs(std::vector<int>& values) {
    std::sort(values.begin(), values.end(), [](int elem1, int elem2){return std::abs(elem1)<std::abs(elem2);});
}

int main() {
    assert(count_greater({1, 5, 10, 20}, 5) == 2);

    std::vector<int> v{1, 2, 3};
    int factor = 3;
    apply_to_all(v, [factor](int x) { return x * factor; });
    assert((v == std::vector<int>{3, 6, 9}));

    auto first = make_counter(10);
    auto second = make_counter(0);
    assert(first() == 10);
    assert(first() == 11);
    assert(second() == 0);
    assert(first() == 12);

    std::vector<int> numbers{-5, 1, -2, 4};
    sort_by_abs(numbers);
    assert((numbers == std::vector<int>{1, -2, 4, -5}));

    std::cout << "OK\n";
}

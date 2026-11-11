/*
  REVIEW 10: templates
  Level 3 | Time: 20 min
  Prepares you for: ../02_pool.cpp and ../05_sparse_set.cpp

  WHAT IT IS
  Templates are generic code. You write the function or class once with a
  type T, and the compiler generates a version for each type you use it with. It
  costs nothing at runtime. There are three kinds of parameter:

  - A type (class T): max_of<int> and max_of<std::string> are two functions the
    compiler generates from the same code.

  - A value (std::size_t N): FixedArray<int, 3> and FixedArray<int, 5> are different
    types. N is known at compile time, so the array can live on the stack
    without new. It's what std::array does.

  - A variadic pack (class... Ts): zero or more types. Used for functions
    that accept any number of arguments. sum_all(1, 2.5, 3) deduces
    Ts = {int, double, int}, and the compiler generates a 3-parameter function.
    values is not an array: you can't index it or loop over it with a for. It
    expands with a fold expression:
      (values + ...)       the compiler turns it into v0 + (v1 + v2)
      (0 + ... + values)   same, but with an initial 0: that way sum_all() compiles
    The parentheses are mandatory. make_unique, emplace_back and std::format
    are variadic: they forward N arguments without knowing how many there are.

  WHAT THE TESTS CHECK
  - max_of<T>: a single function that works for int and for string. It only needs
    operator<.
  - Stack<T>: a class template over vector. pop() when empty throws out_of_range.
  - FixedArray<T, N>: N is a value known at compile time. size() is constexpr
    (checked by static_assert), and at() checks bounds.
  - sum_all: variadic with a fold expression (xs + ...).

  REMEMBER
    template <class T>
    T identity(T value) { return value; }

    template <class T, std::size_t N>   // A parameter can also be a value
    class Foo { T data_[N]; };

    template <class... Ts>              // Variadic: zero or more types
    auto sum(Ts... xs) { return (xs + ...); }  // Fold expression

  Templates usually live in headers: the compiler needs to see the body.
*/
#include <cassert>
#include <cstddef>
#include <iostream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>
#include <cmath>
#include <algorithm>

// Returns the largest element of a non-empty vector of any comparable type.
template <class T>
T max_of(const std::vector<T>& values) {
    if (values.empty()) throw std::out_of_range("max_of: empty vector");
    T best = values[0];
    for (const T& v : values) {
        if (best < v) best = v;
    }
    return best;
}

// Stack on top of std::vector.
template <class T>
class Stack {
public:
    void push(T value) {
        this->items_.push_back(value);
    }

    T pop() {
        if(this->items_.size() < 1) throw std::out_of_range("Stack is empty");
        T elem = items_[items_.size()-1];
        this->items_.pop_back();
        return elem;
    }

    bool empty() const { return items_.empty(); }
    std::size_t size() const { return items_.size(); }

private:
    std::vector<T> items_;
};

// Fixed-size array with bounds checking.
template <class T, std::size_t N>
class FixedArray {
public:
    static constexpr std::size_t size() { return N; }

    T& at(std::size_t i) {
        if(i >= N) throw std::out_of_range("Out of range");
        return data_[i];
    }

private:
    T data_[N]{};
};

// sum_all(1, 2, 3) returns 6.
template <class... Ts>
auto sum_all(Ts... values) {
    return (values + ...);
}

int main() {
    assert(max_of<int>({1, 5, 3}) == 5);
    assert(max_of<std::string>({"ana", "zoe", "leo"}) == "zoe");

    Stack<std::string> stack;
    stack.push("a");
    stack.push("b");
    assert(stack.size() == 2);
    assert(stack.pop() == "b");
    assert(stack.pop() == "a");
    assert(stack.empty());

    bool thrown = false;
    try {
        stack.pop();
    } catch (const std::out_of_range&) {
        thrown = true;
    }
    assert(thrown);

    FixedArray<int, 3> array;
    static_assert(FixedArray<int, 3>::size() == 3);
    array.at(2) = 8;
    assert(array.at(2) == 8);
    assert(array.at(0) == 0);

    thrown = false;
    try {
        array.at(3) = 1;
    } catch (const std::out_of_range&) {
        thrown = true;
    }
    assert(thrown);

    assert(sum_all(1, 2, 3) == 6);

    std::cout << "OK\n";
}

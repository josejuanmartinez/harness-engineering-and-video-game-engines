/*
  REVIEW 01: functions, value, reference and const
  Level 1 | Time: 10 min

  WHAT IT IS
  When you call a function, the argument can be passed in three ways:
  - By value: the function gets a copy.
  - By reference (&): the function works on the original.
  - By const reference: no copy, but it can't be modified either.
  Choosing well avoids expensive copies and makes clear what the function can touch.

  WHAT THE TESTS CHECK
  - swap_ints: that with & the function changes the caller's variables.
  - max_value: read a vector by const& without copying it, also with negatives.
  - double_all: modify a vector in place, by & without const.
  - count_char: walk a string by const&, also an empty one.

  REMEMBER
    void f(int x);                 // copy: f doesn't change the original
    void f(int& x);                // reference: f can change the original
    void f(const std::string& s);  // no copy and no way to modify it (CONST = READONLY)

  Rule of thumb: small types by value; large objects by const&;
  use & without const only if the function must modify the argument.

  TASK
  Fill in the TODOs until the program prints OK.
*/
#include <cassert>
#include <iostream>
#include <string>
#include <vector>

// Swaps the values of a and b.
void swap_ints(int& a, int& b) {
    int temp = b;
    b = a;
    a = temp;
}

// Returns the largest element. You can assume values is not empty.
int max_value(const std::vector<int>& values) {
    int max = values[0];
    for(const auto& v: values) {
        if (v > max) {
            max = v;
        }
    }
    return max;
}

// Doubles each element of the vector in place.
void double_all(std::vector<int>& values) {
    for(auto it = values.begin(); it != values.end(); ++it) {
        *it = *it * 2;
    }
}

// Counts how many times c appears in text.
int count_char(const std::string& text, char c) {
    short counter = 0;
    for(const auto& it: text) {
        counter += it == c? 1 : 0;
    }
    return counter;
}

int main() {
    int a = 1, b = 2;
    swap_ints(a, b);
    assert(a == 2 && b == 1);

    assert(max_value({3, 9, 2}) == 9);
    assert(max_value({-5, -2, -8}) == -2);

    std::vector<int> v{1, 2, 3};
    double_all(v);
    assert((v == std::vector<int>{2, 4, 6}));

    assert(count_char("banana", 'a') == 3);
    assert(count_char("", 'a') == 0);

    std::cout << "OK\n";
}

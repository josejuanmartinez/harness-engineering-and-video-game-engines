/*
  REVIEW 08: move semantics and rule of 5
  Level 2 | Time: 20 min

  WHAT IT IS
  Move semantics: when the source won't be used anymore (a temporary or something marked
  with std::move), instead of copying its data you steal its pointer. It goes from O(n) to
  O(1). The source is left empty but valid. Rule of 5: destructor, copy (x2) and
  move (x2) go together.

  WHAT THE TESTS CHECK
  - Move constructor: b ends up with exactly the same pointer a had, without
    copying anything. a is left with size 0 and data nullptr.
  - Move assignment: c frees its own and steals b's.
  - noexcept: vector only moves its elements when growing if the move is noexcept. If
    not, it copies. The counter copies == 0 shows it.

  REMEMBER
  Moving is stealing the resources of an object that won't be used anymore, instead of
  copying them. std::move doesn't move anything: it just casts to an rvalue so that
  the move constructor gets picked.

    Foo(Foo&& other) noexcept;             // Foo b = std::move(a);
    Foo& operator=(Foo&& other) noexcept;  // b = std::move(a);
    std::exchange(x, new_value);           // puts new_value in x and returns the old value

  The moved-from object must stay valid: its destructor will still run.

  THINK
  - Why does vector only move when growing if the move is noexcept?
  - What is the rule of 0?
*/
#include <algorithm>
#include <cassert>
#include <cstddef>
#include <iostream>
#include <utility>
#include <vector>

class Buffer {
public:
    inline static int copies = 0;

    explicit Buffer(std::size_t size) : size_(size), data_(new int[size]{}) {}

    ~Buffer() { delete[] data_; }

    // a = b
    Buffer(const Buffer& other) : size_(other.size_), data_(new int[other.size_]) {
        std::copy(other.data_, other.data_ + size_, data_);
        ++copies;
    }

    Buffer& operator=(const Buffer&) = delete;

    // std::move
    // Steals size_ and data_. other must be left empty, with no memory.
    Buffer(Buffer&& other) noexcept : size_(std::exchange(other.size_, 0)), data_(std::exchange(other.data_, nullptr)) {

    }

    // Frees its own and steals other's. Must survive a = std::move(a).
    Buffer& operator=(Buffer&& other) noexcept {
      if (this == &other) return *this;           // a = std::move(a): do nothing
      delete[] data_;                             // free what was yours
      data_ = std::exchange(other.data_, nullptr);  // steal, and leave other empty
      size_ = std::exchange(other.size_, 0);
      return *this;
    }

    std::size_t size() const { return size_; }
    const int* data() const { return data_; }
    int& operator[](std::size_t i) { return data_[i]; }

private:
    std::size_t size_;
    int* data_;
};

int main() {
    Buffer a(3);
    a[1] = 5;
    const int* original = a.data();

    Buffer b = std::move(a);
    assert(b.data() == original);  // Same memory: nothing was copied
    assert(b.size() == 3 && b[1] == 5);
    assert(a.size() == 0 && a.data() == nullptr);

    Buffer c(1);
    c = std::move(b);
    assert(c.data() == original);
    assert(b.data() == nullptr);

    std::vector<Buffer> list;
    for (int i = 0; i < 100; ++i) list.push_back(Buffer(4));
    assert(Buffer::copies == 0);  // If the move isn't noexcept, vector will copy

    std::cout << "OK\n";
}

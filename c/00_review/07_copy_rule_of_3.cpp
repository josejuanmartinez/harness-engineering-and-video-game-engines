/*
  REVIEW 07: deep copy and rule of 3
  Level 2 | Time: 20 min

  WHAT IT IS
  A class that owns heap memory has to decide what happens when it's copied. The
  copy the compiler generates copies the pointer (shallow copy): both
  objects end up pointing at the same memory and both free it. A deep copy
  allocates new memory and copies the contents.

  WHAT THE TESTS CHECK
  - Copy constructor (Buffer b = a): b has the same size and the same data.
    Changing b doesn't change a, so the memory isn't shared.
  - Copy assignment (c = a): c already had its own memory. It must free it without
    leaks and end up with a copy of a's.
  - Self-assignment (c = c): if you free before copying, you copy from already
    freed memory. ASan catches it.

  REMEMBER
  If your class manages a resource, the compiler-generated copy only copies
  the pointer. Two objects would free the same memory: double free.

  Rule of 3: if you write a destructor, copy constructor or copy assignment,
  you usually need all three.

    Foo(const Foo& other);             // Foo b = a;
    Foo& operator=(const Foo& other);  // b = a;  (b already existed)

  operator= has to free what it had before and survive a = a.

  THINK
  - What would happen here if you delete the copy constructor and keep the generated one?
  - What's the advantage of copy-and-swap?
*/
#include <algorithm>
#include <cassert>
#include <cstddef>
#include <iostream>

class Buffer {
public:
    explicit Buffer(std::size_t size) : size_(size), data_(new int[size]{}) {}

    ~Buffer() { delete[] data_; }

    // Must allocate its own memory and copy the elements.
    Buffer(const Buffer& other) : size_(0), data_(nullptr) {
        this->size_ = other.size_;
        this->data_ = new int[this->size_]();
        int* ptr = other.data_;
        for(std::size_t i = 0; i< this->size_; i++) {
          this->data_[i] = *ptr;
          ptr++;
        }
    }

    // Must handle a = a and not leak the previous memory.
    Buffer& operator=(const Buffer& other) {
      int* fresh = new int[other.size_];          // 1. new memory (if this throws, *this is untouched)
      for (std::size_t i = 0; i < other.size_; ++i)
          fresh[i] = other.data_[i];              // 2. copy while other.data_ is still alive
      delete[] data_;                             // 3. only now free the old memory
      data_ = fresh;                              // 4. switch over
      size_ = other.size_;
      return *this;
    }

    std::size_t size() const { return size_; }
    int& operator[](std::size_t i) { return data_[i]; }
    const int& operator[](std::size_t i) const { return data_[i]; }

private:
    std::size_t size_;
    int* data_;
};

int main() {
    Buffer a(3);
    a[0] = 7;

    Buffer b = a;
    assert(b.size() == 3);
    assert(b[0] == 7);

    b[0] = 9;
    assert(a[0] == 7);  // Fails if the copy shares memory

    Buffer c(1);
    c = a;
    assert(c.size() == 3);
    assert(c[0] == 7);

    Buffer& alias = c;
    c = alias;  // Self-assignment: a = a
    assert(c.size() == 3);
    assert(c[0] == 7);

    std::cout << "OK\n";
}

/*
  REVIEW 06: constructors, destructors and RAII
  Level 2 | Time: 15 min
  Prepares you for: ../01_arena.cpp and ../02_pool.cpp

  WHAT IT IS
  RAII (Resource Acquisition Is Initialization): ties the lifetime of a resource to that of
  an object. A resource can be memory, a file, a mutex or a GPU texture.
  - The constructor acquires it.
  - The destructor releases it.
  The destructor runs on its own when leaving scope, whether by return, exception or
  anything else. That way you never forget to release. unique_ptr, vector, lock_guard and fstream
  work like this. It's the most important idea in C++ for managing resources.

  WHAT THE TESTS CHECK
  - ScopeTrace: when constructors and destructors run. The test checks
    the exact order: the destructor runs at the block's closing brace, and
    objects in the same scope are destroyed in reverse order (c before a).
  - IntBuffer: a real RAII class. It allocates memory in the constructor and
    frees it in the destructor. The live counter shows that, on leaving the block,
    the buffer destroyed itself, without anyone calling delete.
  - Copying forbidden (= delete): if it could be copied, two objects would free the
    same pointer. That gets fixed in 07.

  REMEMBER
    int* p = new int[n];     // allocates an array
    delete[] p;              // frees an array; delete without [] would be a bug
    Foo(const Foo&) = delete;  // forbids copying

  Local objects are destroyed in reverse order of creation.
*/
#include <cassert>
#include <cstddef>
#include <iostream>
#include <string>
#include <utility>
#include <vector>
#include <format>
#include <cmath>
#include <algorithm>

std::vector<std::string> g_log;

// On creation it adds "+name" to g_log. On destruction it adds "-name".
class ScopeTrace {
public:
    explicit ScopeTrace(std::string name) : name_(std::move(name)) {
        std::string partial = std::format("+{}", name_);
        g_log.push_back(partial);
        std::cout << partial << "\n";
    }

    ~ScopeTrace() {
        g_log.push_back(std::format("-{}", this->name_));
    }

private:
    std::string name_;
};

// Owns an int array on the heap. Cannot be copied.
class IntBuffer {
public:
    inline static int live = 0;  // How many IntBuffers exist right now

    explicit IntBuffer(std::size_t size) : size_(size), data_(nullptr) {
        this->data_ = new int[size_]();
        this->live++;
    }

    ~IntBuffer() {
        delete[] this->data_;
        this->live = std::max(this->live - 1, 0);
    }

    IntBuffer(const IntBuffer&) = delete;
    IntBuffer& operator=(const IntBuffer&) = delete;

    std::size_t size() const { return size_; }
    int& operator[](std::size_t i) { return data_[i]; }

private:
    std::size_t size_;
    int* data_;
};

int main() {
    {
        ScopeTrace outer("a");
        {
            ScopeTrace inner("b");
        }
        ScopeTrace last("c");
    }
    assert((g_log == std::vector<std::string>{"+a", "+b", "-b", "+c", "-c", "-a"}));

    {
        IntBuffer buffer(4);
        assert(IntBuffer::live == 1);
        buffer[2] = 42;
        assert(buffer[2] == 42);
        assert(buffer[0] == 0);
    }
    assert(IntBuffer::live == 0);

    std::cout << "OK\n";
}

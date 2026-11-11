/*
  01: arena (frame allocator)
  Time: 10 min

  THE IDEA
  new and malloc are slow and fragment memory, and a game creates thousands of temporary
  things every frame. An arena asks for one big block a single time and then hands out
  pieces by advancing an offset: each alloc is just an addition.
  You can't free individual pieces. At the end of the frame you call reset() and everything
  is freed at once. It's the simplest allocator and one of the most used in engines.

  WHAT THE TESTS CHECK
  - alloc respects the requested alignment (1, 8 and 64): the returned address is a
    multiple of align.
  - create<T> constructs with placement new inside the arena.
  - If it doesn't fit, it returns nullptr instead of running past the buffer.
  - reset frees everything at once in O(1). The next allocation gets the first
    address again.

  ALIGNMENT (what you need for alloc)
  Every type requires its address to be a multiple of some number: its alignment.
  - A double goes on multiples of 8 (alignof(double) == 8).
  - If you put it on an odd address, on x86 it's slower, and on other CPUs it crashes.
  That's why alloc can't return the offset as is. First it rounds it up to the next
  multiple of align.

  Round up to a multiple of align (align is a power of 2):
      align_up(x, align) = (x + align - 1) & ~(align - 1)
  Example with align 8: align_up(13, 8) = 16, align_up(16, 8) = 16.
  Why it works: adding align - 1 takes you past the next multiple (unless you
  were already on one), and & ~(align - 1) zeroes the low bits, which drops you to the
  multiple.

  Align the ADDRESS, not the offset: base + offset. The buffer itself may not
  start on a multiple of 64. To do math with an address, convert it
  to an integer:
      auto base = reinterpret_cast<std::uintptr_t>(buffer_.get());

  PLACEMENT NEW (for create)
  new T(args) does two things: allocates memory and constructs the object. Placement new
  only constructs, in memory you already have:
      T* p = new (memory) T{args...};   // allocates nothing
  This is how an allocator separates "where the memory comes from" from "creating the object".

  REMEMBER
    An arena is a block of memory plus an offset. alloc = align and advance the offset.
    There's no individual free: reset() frees everything at once (e.g. at the end of the frame).
    new (p) T{args...}   // constructs in arena memory

  INTERVIEW QUESTIONS
  At the end of the file, marked with TODO: QUESTION.
*/
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <iostream>
#include <memory>
#include <new>
#include <type_traits>
#include <utility>

class Arena {
public:
    explicit Arena(std::size_t capacity)
        : buffer_(std::make_unique<std::byte[]>(capacity)), capacity_(capacity) {}

    // Returns memory aligned to align, or nullptr if it doesn't fit.
    void* alloc(std::size_t size, std::size_t align) {
        // TODO: align the ADDRESS (not just the offset) with align_up (see ALIGNMENT above)
        return nullptr;
    }

    template <class T, class... Args>
    T* create(Args&&... args) {
        static_assert(std::is_trivially_destructible_v<T>, "reset() doesn't call destructors");
        // TODO: alloc(sizeof(T), alignof(T)) and placement new
        return nullptr;
    }

    void reset() { /* TODO */ }
    std::size_t used() const { return offset_; }

private:
    std::unique_ptr<std::byte[]> buffer_;
    std::size_t capacity_;
    std::size_t offset_ = 0;
};

struct Vec3 { float x, y, z; };

int main() {
    Arena arena(256);

    char* c = static_cast<char*>(arena.alloc(1, 1));
    assert(c != nullptr && arena.used() >= 1);

    auto* d = static_cast<double*>(arena.alloc(sizeof(double), alignof(double)));
    assert(d != nullptr);
    assert(reinterpret_cast<std::uintptr_t>(d) % alignof(double) == 0);

    void* line = arena.alloc(64, 64);
    assert(line != nullptr && reinterpret_cast<std::uintptr_t>(line) % 64 == 0);

    Vec3* v = arena.create<Vec3>(1.0f, 2.0f, 3.0f);
    assert(v != nullptr && v->y == 2.0f);

    assert(arena.alloc(1000, 8) == nullptr);    // doesn't fit: nullptr, no crash

    arena.reset();
    assert(arena.used() == 0);
    assert(arena.alloc(1, 1) == c);             // starts again from the beginning
    std::cout << "OK\n";
}

/*
  INTERVIEW QUESTIONS
  Write your answer under each one, in 2-3 sentences, then say it out loud.
  The hint is the minimum your answer must cover. Cover it before answering.

  TODO: QUESTION 1. What do you save with an arena compared to new in a hot path?
  Hint: new has to search for a free gap, sometimes take a heap lock, and it
    fragments memory. The arena just adds to an offset.
  Answer:

  TODO: QUESTION 2. reset() doesn't call destructors. Which types can you safely put in an
    arena?
  Hint: Trivially destructible ones (plain data structs: floats, ints, arrays). A
    std::string would leave its memory unfreed.
  Answer:

  TODO: QUESTION 3. Why do Unity and Unreal recommend not allocating every
    frame, each for a different reason?
  Hint: Unity: the C# GC (Boehm, non-generational) causes pauses. Unreal: the
    UObject GC and heap fragmentation. In both, new/malloc is slow in a hot
    path.
  Answer:

  TODO: QUESTION 4. What equivalent to your arena do Unity and Unreal have?
  Hint: Unity: Allocator.Temp (freed at the end of the frame). Unreal: FMemStack /
    FMemMark.
  Answer:

  TODO: QUESTION 5. [Design: game and render thread] The renderer runs one frame behind.
    What are two frame arenas (double buffering) for?
  Hint: While the game thread writes frame N into one arena, the renderer reads
    frame N-1 from the other. They don't step on each other, and when done they swap
    and the old one is reset.
  Answer:

  TODO: QUESTION 6. [Design: ML inference in the game] How do you avoid allocations when
    passing data to the model every frame?
  Hint: You allocate the input and output buffers (tensors) once at the start and
    reuse them every frame, like an arena.
  Answer:

*/

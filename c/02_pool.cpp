/*
  02: pool allocator with a free list
  Time: 10 min

  THE IDEA
  A pool is useful when you create and destroy many objects of the same type with different
  lifetimes (bullets, particles, enemies). It reserves N slots up front, and the free ones form a
  linked list: creating pops the first one off the list and destroying pushes it back. Both
  are O(1) and don't call new.
  The trick: a free slot holds no object, so its own memory can store the pointer to the
  next free one. That's why Slot is a union.

  WHAT THE TESTS CHECK
  - create constructs objects in fixed slots (alive == 3) and returns nullptr if the
    pool is full.
  - destroy calls the destructor (alive goes down) and returns the slot to the free list.
  - d == b: the next allocation reuses exactly the slot that was freed. The free
    list is a LIFO stack.

  REMEMBER
    A pool has N slots of the same size. The free slots form a linked list
    stored INSIDE the slots themselves, so it uses no extra memory.
    alignas(T) std::byte storage[sizeof(T)];   // room for a T without constructing it
    T* p = new (storage) T{args...};           // placement new: constructs there (see 01)
    p->~T();                                   // destroys without freeing

  Since you constructed with placement new, you can't do delete p: delete would free
  memory that didn't come from new. You call the destructor by hand and the slot goes
  back to the free list.

  INTERVIEW QUESTIONS
  At the end of the file, marked with TODO: QUESTION.
*/
#include <cassert>
#include <cstddef>
#include <iostream>
#include <new>
#include <utility>

template <class T, std::size_t N>
class Pool {
    union Slot {
        Slot* next;                                // if the slot is free
        alignas(T) std::byte storage[sizeof(T)];   // if it's occupied
    };

public:
    Pool() {
        // TODO: chain all the slots into the free list (slots_[i].next = &slots_[i + 1])
        //       and point free_ at the first one
      for(int i=0; i<this->slots_.size() - 1;i++) {
        this->slots_[i].next = this->slots_[i+1];
      }
      this->free = this->slots_[0];
    }

    template <class... Args>
    T* create(Args&&... args) {
        if(this->free_ == nullptr) return nullptr;
        Slot* first = this->free_;
        free_ = first->next;
        return new (first->storage) T(std::forward)
        return nullptr;
    }

    void destroy(T* p) {
        // TODO: call the destructor and return the slot to the front of the free list
        p->~T();
        Slot* s =

    }

private:
    Slot slots_[N];
    Slot* free_ = nullptr;
};

struct Bullet {
    static inline int alive = 0;
    float x, y;
    Bullet(float px, float py) : x(px), y(py) { ++alive; }
    ~Bullet() { --alive; }
};

int main() {
    Pool<Bullet, 3> pool;
    Bullet* a = pool.create(1.0f, 2.0f);
    Bullet* b = pool.create(3.0f, 4.0f);
    Bullet* c = pool.create(5.0f, 6.0f);
    assert(a && b && c && Bullet::alive == 3);
    assert(a->x == 1.0f && c->y == 6.0f);
    assert(pool.create(0.0f, 0.0f) == nullptr);    // full

    pool.destroy(b);
    assert(Bullet::alive == 2);
    Bullet* d = pool.create(7.0f, 8.0f);
    assert(d == b);                                // reuses the freed slot

    pool.destroy(a);
    pool.destroy(c);
    pool.destroy(d);
    assert(Bullet::alive == 0);
    std::cout << "OK\n";
}

/*
  INTERVIEW QUESTIONS
  Write your answer under each one, in 2-3 sentences, then say it out loud.
  The hint is the minimum your answer must cover. Cover it before answering.

  TODO: QUESTION 1. Pool or arena? When do you use each one?
  Hint: Pool: objects of the same size that are born and die at different times
    (bullets, particles). Arena: temporary things that all die at once (at the end
    of the frame).
  Answer:

  TODO: QUESTION 2. How would you detect a double free in your pool?
  Hint: An alive/dead flag per slot (or a memory pattern in debug). If destroy
    gets a slot that's already free, assert.
  Answer:

  TODO: QUESTION 3. What if several threads use the pool at the same time?
  Hint: A lock (simple, but there's contention), one pool per thread (the usual), or an
    atomic free list with CAS (watch out for the ABA problem).
  Answer:

  TODO: QUESTION 4. What equivalents do engines have?
  Hint: UnityEngine.Pool (object pooling, to avoid generating garbage for the GC). In
    Unreal, FMallocBinned: the general allocator is pools by size. Godot:
    PagedAllocator.
  Answer:

  TODO: QUESTION 5. In Unity, why pool bullets instead of using Instantiate and
    Destroy?
  Hint: Instantiate/Destroy create garbage and native objects. The GC ends up kicking in
    mid-game and causes a hitch. With a pool you reuse and no new objects
    are allocated.
  Answer:

*/

/*
  03: generational handles (slot map)
  Time: 15 min

  THE IDEA
  The problem: enemy A stores a pointer to enemy B. B dies and is deleted, and A's pointer
  now points to freed memory (a dangling pointer). Using it is a crash, or something worse.
  Engines solve this with handles instead of pointers. A handle is {index, generation}:
  the index says which slot the object is in and the generation, which version of the slot it is. Every
  time a slot is freed, its generation goes up. If your handle has an old generation,
  get() returns nullptr, so you know the object no longer exists instead of crashing.

  WHAT THE TESTS CHECK
  - get with a valid handle returns the object.
  - After remove, the old handle returns nullptr instead of a dangling pointer.
  - troll reuses the orc's index but with another generation, so the orc's
    handle is still invalid.
  - remove with an old handle doesn't delete the troll that now occupies the slot.
  - An out-of-range index (99) returns nullptr, no crash.

  REMEMBER
    A handle is {index, generation}. Each slot stores its current generation.
    On delete, the slot's generation goes up: old handles stop matching and
    get() returns nullptr instead of a dangling pointer.

  INTERVIEW QUESTIONS
  At the end of the file, marked with TODO: QUESTION.
*/
#include <cassert>
#include <cstdint>
#include <iostream>
#include <optional>
#include <string>
#include <vector>

struct Handle {
    std::uint32_t index = 0;
    std::uint32_t generation = 0;
};

template <class T>
class SlotMap {
    struct Slot {
        std::optional<T> value;           // empty if the slot is free
        std::uint32_t generation = 0;
    };

public:
    Handle insert(T value) {
        // TODO: if there are indices in free_, reuse one; otherwise, add a new slot.
        //       Return {index, current generation of the slot}
        return {};
    }

    T* get(Handle h) {
        // TODO: nullptr if the index is out of range, if the generation doesn't match
        //       or if the slot is empty
        return nullptr;
    }

    void remove(Handle h) {
        // TODO: if the handle is valid, empty the slot, bump its generation
        //       and store the index in free_
    }

private:
    std::vector<Slot> slots_;
    std::vector<std::uint32_t> free_;
};

int main() {
    SlotMap<std::string> enemies;
    Handle orc = enemies.insert("orc");
    Handle elf = enemies.insert("elf");
    assert(enemies.get(orc) && *enemies.get(orc) == "orc");
    assert(enemies.get(elf) && *enemies.get(elf) == "elf");

    enemies.remove(orc);
    assert(enemies.get(orc) == nullptr);         // the old handle is no longer valid

    Handle troll = enemies.insert("troll");      // reuses the orc's slot
    assert(troll.index == orc.index);
    assert(troll.generation != orc.generation);
    assert(enemies.get(orc) == nullptr);         // still invalid
    assert(*enemies.get(troll) == "troll");

    enemies.remove(orc);                         // removing with an old handle does nothing
    assert(enemies.get(troll) && *enemies.get(troll) == "troll");

    assert(enemies.get(Handle{99, 0}) == nullptr);
    std::cout << "OK\n";
}

/*
  INTERVIEW QUESTIONS
  Write your answer under each one, in 2-3 sentences, then say it out loud.
  The hint is the minimum your answer must cover. Cover it before answering.

  TODO: QUESTION 1. Why is a handle better than a T* or a shared_ptr for
    referencing entities?
  Hint: T* dangles if the object dies. shared_ptr has a cost (atomic refcount)
    and blurs who the owner is, and it keeps alive objects the game already wanted
    to delete. The handle detects that the object has died and returns nullptr.
  Answer:

  TODO: QUESTION 2. How long is the T* returned by get() valid?
  Hint: Until the internal vector grows (realloc) or that object is deleted. Use it
    right away, don't store it.
  Answer:

  TODO: QUESTION 3. If you pack the handle into 32 bits, how many bits do you give the index and
    how many the generation?
  Hint: For example, 20 for the index (1M objects) and 12 for the generation (4096
    reuses before wrapping around). It's a trade-off: more objects or more
    safety.
  Answer:

  TODO: QUESTION 4. How do engines do it?
  Hint: Unreal: TWeakObjectPtr = index + serial in GUObjectArray. Unity DOTS: Entity
    = index + version. Godot: RID in the servers.
  Answer:

  TODO: QUESTION 5. [Unreal] Why is a UObject* stored without UPROPERTY a bug?
  Hint: Unreal's GC only follows the references it knows about through reflection
    (UPROPERTY, TObjectPtr). If it doesn't see it, it can delete the object and your pointer is left
    dangling.
  Answer:

  TODO: QUESTION 6. [Unity] What is "fake null"?
  Hint: When you destroy a GameObject, the native C++ object dies but the C#
    wrapper stays alive. Unity overloads == so it compares as null, but ?. and ?? don't
    use that ==, so they don't detect it.
  Answer:

  TODO: QUESTION 7. [Design: 100k entities] How does an entity store a reference to
    another one (its target, its parent)?
  Hint: With a handle (index + generation), never with a pointer. If the target
    dies, get() returns nullptr and the entity handles it.
  Answer:

*/

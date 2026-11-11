/*
  05: sparse set (the storage of an ECS)
  Time: 15 min

  THE IDEA
  In an ECS (Entity Component System), an entity is just a number. Its data (Position,
  Velocity...) lives in separate arrays per component type, and each system (for example,
  the movement one) walks those arrays. It's the SoA idea from exercise 04 taken to an engine.
  The sparse set is how each component type is stored:
  - components_: the components one after another, with no gaps (iterating is very fast)
  - dense_: which entity each component belongs to
  - sparse_: given an entity, at which position its component is
  To delete without leaving gaps, the last one moves into the deleted spot (swap-and-pop).

  WHAT THE TESTS CHECK
  - add and has: sparse is indexed by entity; dense keeps the components together.
  - movement_system walks only the entities with Position and Velocity (7 is
    ignored).
  - remove in the middle: swap-and-pop. The last one fills the gap and its index in sparse
    is updated (4 is still accessible).
  - remove of the last one and of an entity that doesn't exist: edge cases.
  - The final loop: the components are still contiguous and aligned with entities().

  REMEMBER
    sparse[entity] -> position in dense (or INVALID)
    dense[i]       -> which entity is at position i
    components[i]  -> the component of dense[i]; it's contiguous, so iterating is very fast
    Delete in O(1) with swap-and-pop: move the last one to the deleted position and fix
    its entry in sparse.

  INTERVIEW QUESTIONS
  At the end of the file, marked with TODO: QUESTION.
*/
#include <cassert>
#include <cstdint>
#include <iostream>
#include <limits>
#include <vector>

using Entity = std::uint32_t;

template <class T>
class Storage {
public:
    static constexpr std::uint32_t INVALID = std::numeric_limits<std::uint32_t>::max();

    void add(Entity e, T component) {
        // TODO: grow sparse_ if needed (filling with INVALID),
        //       point sparse_[e] at the end of dense_ and append e and component
    }

    bool has(Entity e) const {
        return false;  // TODO
    }

    T* get(Entity e) {
        return nullptr;  // TODO
    }

    void remove(Entity e) {
        // TODO: swap-and-pop. Careful if e is already the last one
    }

    std::size_t size() const { return dense_.size(); }
    const std::vector<Entity>& entities() const { return dense_; }
    std::vector<T>& components() { return components_; }

private:
    std::vector<std::uint32_t> sparse_;
    std::vector<Entity> dense_;
    std::vector<T> components_;
};

struct Position { float x, y; };
struct Velocity { float vx, vy; };

// Moves the entities that have Position AND Velocity.
void movement_system(Storage<Position>& pos, Storage<Velocity>& vel, float dt) {
    // TODO: walk vel (here it's the smaller one) and look up each entity's Position
}

int main() {
    Storage<Position> pos;
    Storage<Velocity> vel;
    for (Entity e = 0; e < 5; ++e) pos.add(e, {0.0f, 0.0f});
    vel.add(1, {1.0f, 0.0f});
    vel.add(3, {0.0f, 2.0f});
    vel.add(7, {5.0f, 5.0f});       // 7 has no Position: the system ignores it

    assert(pos.has(4) && !pos.has(9) && !vel.has(0));

    movement_system(pos, vel, 1.0f);
    assert(pos.get(1)->x == 1.0f);
    assert(pos.get(3)->y == 2.0f);
    assert(pos.get(0)->x == 0.0f);

    pos.remove(1);                  // delete in the middle
    assert(!pos.has(1) && pos.size() == 4);
    assert(pos.has(4) && pos.get(4)->x == 0.0f);   // the last one moved and is still accessible
    pos.remove(4);                  // delete the last one
    assert(!pos.has(4) && pos.size() == 3);
    pos.remove(42);                 // doesn't exist: does nothing
    assert(pos.size() == 3);

    // The components are still contiguous and aligned with dense
    for (std::size_t i = 0; i < pos.size(); ++i)
        assert(pos.get(pos.entities()[i]) == &pos.components()[i]);
    std::cout << "OK\n";
}

/*
  INTERVIEW QUESTIONS
  Write your answer under each one, in 2-3 sentences, then say it out loud.
  The hint is the minimum your answer must cover. Cover it before answering.

  TODO: QUESTION 1. Why does swap-and-pop invalidate pointers to components?
  Hint: On delete, the last component moves into the gap. Any pointer to that
    last one now points to a place that isn't its own. That's why entities and
    indices are used, not pointers.
  Answer:

  TODO: QUESTION 2. With two components, why is it better to iterate the smaller
    storage?
  Hint: You walk fewer elements and for each one you ask has() on the other, which is
    O(1). Iterating the big one would do useless work.
  Answer:

  TODO: QUESTION 3. Sparse sets vs archetypes (Unity DOTS, Unreal Mass): what does
    each one optimize?
  Hint: Sparse set: adding and removing components is cheap (EnTT). Archetypes:
    entities with the same components together in chunks, so iterating several
    components is faster, but changing components moves the entity to another chunk.
  Answer:

  TODO: QUESTION 4. How do you avoid deleting entities while a system is iterating?
  Hint: Command buffer: you record "delete X" and apply it at the end of the system or the
    frame (EntityCommandBuffer in Unity).
  Answer:

  TODO: QUESTION 5. [Design: 100k entities] How do you run systems in parallel
    without data races?
  Hint: Each system declares which components it reads and writes. Two systems that write
    the same thing don't run at the same time. A job system with dependencies orders them. Unity has a
    safety system that checks it.
  Answer:

  TODO: QUESTION 6. [Design: 100k entities] How do Unity DOTS, Unreal Mass and
    Godot do it?
  Hint: DOTS: archetypes in 16 KB chunks + Job System + Burst. Mass: archetypes,
    for crowds. Godot: not an ECS; it uses nodes plus servers.
  Answer:

  TODO: QUESTION 7. [Design: game and render thread] How do you split the rest of the frame's
    work across cores?
  Hint: Job system: split the work into small tasks with dependencies (a graph)
    and a thread pool runs them. Unreal TaskGraph, Unity Job System, Godot
    WorkerThreadPool.
  Answer:

*/

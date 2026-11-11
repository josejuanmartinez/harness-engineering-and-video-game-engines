/*
  06: events with safe subscribe and unsubscribe during emit
  Time: 10 min | Topics: lambdas, std::function, reentrancy

  THE IDEA
  An event system: something happens (the player takes damage) and everyone subscribed
  is notified (the UI, the sound, the achievements) without the damage code having to know
  them. It's the observer pattern.
  The hard part: while you walk the list of subscribers, one of them can unsubscribe
  or subscribe someone else. If the vector changes during the walk, the walk breaks or, worse,
  the function currently running is destroyed. Here you solve it by marking the changes and
  applying them when emit finishes.

  WHAT THE TESTS CHECK
  - Basic subscribe and emit.
  - A listener that unsubscribes inside emit: it must not break the iteration (it's
    the classic bug of invalidating the vector while you walk it).
  - A listener that subscribes another one inside emit: the new one is not called in that
    same emit, only in the next one.
  - count and unsubscribe: 3 remain and, after removing a, total doesn't change.

  REMEMBER
    std::function<void(int)> f = [&](int x) { ... };   // stores any callable
    If you capture by reference or this, the object must outlive the subscription.
    The classic problem: a listener unsubscribes (or subscribes another one) INSIDE emit,
    and the vector changes while you walk it. A push_back can reallocate and destroy the
    std::function that is currently running.

  INTERVIEW QUESTIONS
  At the end of the file, marked with TODO: QUESTION.
*/
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <functional>
#include <iostream>
#include <vector>

class Event {
public:
    using Id = std::uint32_t;

    Id subscribe(std::function<void(int)> fn) {
        // TODO: if you are inside emit, put it in pending_, not in listeners_
        return 0;
    }

    void unsubscribe(Id id) {
        // TODO: set alive = false. If you are NOT inside emit, clean up right away
    }

    void emit(int value) {
        // TODO: call the live listeners, walking by index. When done,
        //       move pending_ into listeners_ and erase the marked ones (std::erase_if)
    }

    std::size_t count() const {
        return 0;  // TODO: live listeners (in listeners_ and in pending_)
    }

private:
    struct Listener {
        Id id;
        std::function<void(int)> fn;
        bool alive = true;
    };
    std::vector<Listener> listeners_;
    std::vector<Listener> pending_;      // subscriptions made during emit
    Id next_id_ = 1;
    bool emitting_ = false;
};

int main() {
    Event on_damage;
    int total = 0;
    Event::Id a = on_damage.subscribe([&](int d) { total += d; });
    on_damage.emit(10);
    assert(total == 10);

    // A listener that unsubscribes itself inside emit
    Event::Id self = 0;
    int once_calls = 0;
    self = on_damage.subscribe([&](int) { ++once_calls; on_damage.unsubscribe(self); });

    // A listener that subscribes another one inside emit
    int late_calls = 0;
    bool added = false;
    on_damage.subscribe([&](int) {
        if (!added) { added = true; on_damage.subscribe([&](int) { ++late_calls; }); }
    });

    on_damage.emit(1);
    assert(total == 11 && once_calls == 1);
    assert(late_calls == 0);            // it subscribed during this emit: not yet
    on_damage.emit(1);
    assert(total == 12 && once_calls == 1 && late_calls == 1);
    assert(on_damage.count() == 3);     // a, the one that subscribes, and the late one

    on_damage.unsubscribe(a);
    on_damage.emit(100);
    assert(total == 12);
    std::cout << "OK\n";
}

/*
  INTERVIEW QUESTIONS
  Write your answer under each one, in 2-3 sentences, then say it out loud.
  The hint is the minimum that has to come up. Cover it before answering.

  TODO: QUESTION 1. In emit: copy the listener list, or mark removals and
    clean up later? What does each option cost?
  Hint: Copy: simple and safe, but allocates on every emit. Mark and clean: no
    allocations, but more logic (and careful with an emit inside another emit).
  Answer:

  TODO: QUESTION 2. How much does a std::function cost?
  Hint: Type erasure: an indirect call, and if the lambda captures a lot, an
    allocation when creating it. Avoided in hot paths.
  Answer:

  TODO: QUESTION 3. What advantage do Godot signals have over your Event?
  Hint: They disconnect on their own when the receiving object is freed, so no
    callback is left pointing to a dead object.
  Answer:

  TODO: QUESTION 4. [Unreal] Single, multicast and dynamic delegates: what is each one?
  Hint: Single: one listener. Multicast: several. Dynamic: goes through the reflection
    system (UFUNCTION), so it can be serialized and used from Blueprints, but
    it's slower.
  Answer:

  TODO: QUESTION 5. [Unreal] What do UCLASS, UPROPERTY and UFUNCTION do?
  Hint: They are macros read by the Unreal Header Tool to generate reflection code
    (.generated.h). That's what makes the editor, serialization, Blueprints,
    replication and the GC work.
  Answer:

  TODO: QUESTION 6. [Design: game and render thread] How do you send commands from the game
    thread to the render thread?
  Hint: A command queue: the game thread pushes and the render thread pops.
    A mutex protecting a deque is enough. Unreal: ENQUEUE_RENDER_COMMAND. Godot:
    CommandQueueMT.
  Answer:

*/

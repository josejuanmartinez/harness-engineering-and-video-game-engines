/*
  09: deterministic physics
  Time: 10 min | Each TODO is a single line

  THE IDEA
  Deterministic = same inputs, same result, BIT FOR BIT, on every run
  and on every machine. You need it for:
  - Lockstep multiplayer (RTS) and rollback (fighting games, GGPO): only the inputs
    travel over the network, and each machine simulates. If a single bit differs, the
    matches go out of sync (desync).
  - Replays: you store the inputs, not the states.
  - Debugging: a bug that always reproduces the same way.

  Where NON-determinism comes from, and how to fix it:
  1. Variable dt. At 60 FPS or at 30 FPS the physics gives different results.
     → Fixed timestep (exercise 07). Physics only advances in steps of dt.
  2. Measuring time in float. Adding 1/60 many times accumulates error, and two
     machines can run 59 or 60 steps.
     → Count time in integer ticks (microseconds or step number).
  3. The order of float operations. (a + b) + c may not equal
     a + (b + c). So the result changes if:
     - The compiler reorders (-ffast-math, /fp:fast) or fuses a*b+c into an FMA.
     - Several threads add in a different order each time.
     → Strict flags (/fp:precise or /fp:strict, no fast-math), the same binary
       on every machine, reductions in a fixed order.
  4. Functions like sin, cos or exp are not identical across libraries and CPUs (sqrt
     is: IEEE requires it to be exact).
     → Your own implementation, or fixed-point arithmetic (integers), which is
       deterministic everywhere.
  5. The order you walk objects in: unordered_map, pointers as keys,
     creation order across threads.
     → Walk in a stable order (by id). Sort before resolving collisions.
  6. Randomness: global rand(), time-based seeds.
     → The simulation's own RNG, with a fixed seed, as part of the state.

  In the engines:
  - Unity Physics (DOTS) is deterministic on the same platform and build.
  - Photon Quantum uses fixed point to be deterministic across platforms.
  - Box2D v3 is designed to be deterministic across platforms.
  - PhysX (classic Unity) and Chaos (Unreal) don't guarantee it across machines. That's
    why Unreal multiplayer replicates states from the server instead of
    doing lockstep.

  WHAT THE TESTS CHECK
  - step: one semi-implicit Euler step (2 lines: velocity and position).
  - Demo 1: the same 1 s fall with dt 1/30 and with dt 1/60 gives different
    positions. That's why variable dt is not deterministic.
  - Demo 2, simulate_fixed: fixed timestep with time in INTEGER ticks (3 lines).
    Two machines with different FPS (20 ms and 10 ms frames) run the same
    steps and give the same result bit for bit.
  - Demo 3: (a + b) + c != a + (b + c) with float (2 lines).

  REMEMBER
    v += a * dt;   x += v * dt;            // semi-implicit Euler: first v, then x
    accumulator += frame_time;              // fixed timestep (same as 07)
    while (accumulator >= dt) { step(dt); accumulator -= dt; }

  INTERVIEW QUESTIONS
  At the end of the file, marked with TODO: QUESTION.
*/
#include <cassert>
#include <cstdint>
#include <iostream>

struct Body {
    float y = 100.0f;
    float vy = 0.0f;
};


/*
t=1
sec   kGravity   vy     y
0     -9.8     0       0
1     -9.8   -9.8    -9.8
2     -9.8  -19.6   -29.4
3     -9.8  -29.4   -58.8
*/

void step(Body& b, float dt) {
    constexpr float kGravity = -9.8f;
    // TODO: add gravity times dt to b.vy
    b.vy += kGravity*dt;
    // TODO: add velocity times dt to b.y
    b.y += b.vy*dt;
}

// Simulates total_ms of time with frames of frame_ms, in fixed 10 ms steps.
// Time is counted in integers: no accumulated error.
Body simulate_fixed(int total_ms, int frame_ms) {
    constexpr int kStepMs = 10;
    constexpr float kDt = kStepMs / 1000.0f;
    Body b;
    int accumulator_ms = 0;
    for (int t = 0; t < total_ms; t += frame_ms) {
        // TODO: add this frame's time to the accumulator
        accumulator_ms += frame_ms;
        while (accumulator_ms >= kStepMs) {
            // TODO: run a physics step with kDt
            step(b, kDt);
            // TODO: subtract a step from the accumulator (otherwise the while never ends)
            accumulator_ms -= kStepMs;
        }
    }
    return b;
}

int main() {
    // Demo 1: variable dt → different results depending on FPS.
    Body at30, at60;
    for (int i = 0; i < 30; ++i) step(at30, 1.0f / 30.0f);
    for (int i = 0; i < 60; ++i) step(at60, 1.0f / 60.0f);
    std::cout << "variable dt:  30 FPS y = " << at30.y << ", 60 FPS y = " << at60.y << '\n';
    assert(at30.y != at60.y);

    // Demo 2: fixed timestep + integer ticks → identical bit for bit.
    Body slow = simulate_fixed(1000, 20);  // machine at 50 FPS
    Body fast = simulate_fixed(1000, 10);  // machine at 100 FPS
    std::cout << "fixed step:   50 FPS y = " << slow.y << ", 100 FPS y = " << fast.y << '\n';
    assert(slow.y == fast.y && slow.vy == fast.vy);

    // Demo 3: the order of the additions changes the result.
    volatile float a = 1e8f, b = -1e8f, c = 1.0f;  // volatile: so the compiler doesn't precompute it
    float left = (a + b) + c;   // TODO: (a + b) + c
    float right = a + (b+c);  // TODO: a + (b + c). Note that -1e8 + 1 rounds to -1e8
    (void)a; (void)b; (void)c;
    std::cout << "(a+b)+c = " << left << ", a+(b+c) = " << right << '\n';
    assert(left != right);

    std::cout << "OK\n";
}

/*
  INTERVIEW QUESTIONS
  Write your answer under each one, in 2-3 sentences, then say it out loud.
  The hint is the minimum that has to come up. Cover it before answering.

  TODO: QUESTION 1. Why does lockstep send inputs and not positions?
  Hint: Inputs are a few bytes per player per frame. The positions of thousands
    of units don't fit in the bandwidth. Each machine simulates the same thing.
  Answer:

  TODO: QUESTION 2. If your physics is deterministic but the render isn't, is that a problem?
  Hint: No. The render is not part of the simulation state: it only draws it.
  Answer:

  TODO: QUESTION 3. Why does parallelizing physics complicate determinism?
  Hint: Threads finish in a different order on each run and float additions
    give different results depending on the order. You have to fix the order of the reductions.
  Answer:

  TODO: QUESTION 4. [Unreal] How does multiplayer work if it isn't deterministic?
  Hint: Authoritative server: the server simulates and replicates properties to the
    clients, with RPCs (Server, Client, NetMulticast). It's not lockstep.
  Answer:

  TODO: QUESTION 5. [Design: ML inference in the game] How do you keep
    determinism in multiplayer if a model decides what the NPCs do?
  Hint: The model runs only on the server and the result is replicated. If it were
    lockstep, inference would have to be bit-for-bit identical on every machine, which
    is very hard with float on the GPU.
  Answer:

  TODO: QUESTION 6. [Harness] How would you use determinism to test a game?
  Hint: You record the inputs and replay the exact match to reproduce a bug. In
    CI, bots that play through an API (Gauntlet, Unity Test Framework, ML-Agents) and
    performance gates.
  Answer:

  TODO: QUESTION 7. [Harness] Tell your story in 2 minutes.
  Hint: The problem, a low-level technical decision (concurrency, cache,
    latency or failures) and the measured result.
  Answer:

*/

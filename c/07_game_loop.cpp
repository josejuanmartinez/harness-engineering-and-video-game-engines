/*
  07: game loop with fixed timestep
  Time: 15 min

  ======================================================================
  WHAT IT IS
  ======================================================================
  A game repeats this loop nonstop:  read input -> update physics -> draw.
  Each pass is a "frame", and each frame takes a DIFFERENT amount of time (16 ms, 20 ms, 8 ms...)
  depending on how loaded the PC is.

  Problem: if you do  x += v * frame_time  with that variable time, the physics depends on
  the FPS. On a slow PC the steps are bigger: the object goes through walls, the
  jumps come out different and two machines don't give the same result (goodbye deterministic
  multiplayer).

  Solution, the FIXED TIMESTEP: physics ALWAYS advances in steps of the same size,
  dt = 1/60 s (about 16.67 ms). Rendering, on the other hand, runs as fast as it can.

  To connect the two you use a time "bank", the ACCUMULATOR:
    1. At the start of the frame you put the real time that has passed into the bank.
    2. While the bank holds at least one dt, you take out a dt and run ONE physics step.
    3. What's left over (less than a dt) stays in the bank for the next frame.

  EXAMPLE WITH NUMBERS (dt = 16.67 ms, the game runs at 100 FPS: each frame lasts 10 ms)
    frame 1: bank = 0 + 10     = 10 ms  -> 10 < 16.67, 0 steps.  10 ms left.
    frame 2: bank = 10 + 10    = 20 ms  -> 1 step (20 - 16.67).  3.33 ms left.
    frame 3: bank = 3.33 + 10  = 13.33  -> 0 steps.              13.33 ms left.
    frame 4: bank = 23.33               -> 1 step.               6.67 ms left.
  On average you get 60 steps per second, which is what we want.

  INTERPOLATION. In frame 1 there was no step, so if you draw current_ the object
  stays still in that frame and jumps in the next one: it looks jerky. That's why
  you also keep the PREVIOUS state (previous_) and draw a point in between:
      alpha = accumulator / dt        // 0 to 1: how far we are toward the next step
      x_draw = previous.x + (current.x - previous.x) * alpha
  If 3.33 ms of 16.67 are left, alpha = 0.2 and you draw 20% of the way between the two.

  SPIRAL OF DEATH. If a frame takes 5 s (a breakpoint, a disk load), the
  bank would have 300 pending steps. Running them all makes the NEXT frame slow
  too, and even more pile up: the game never recovers. Solution: clamp frame_time
  to a maximum (max_frame = 0.25 s, which is 15 steps). Some game time is lost,
  but the game stays alive.

  ======================================================================
  WHAT THE TESTS CHECK (see main)
  ======================================================================
  Loop a:  frame(1/30) returns 2.
           1/30 s = 33.3 ms, the bank fits two steps of 16.67 ms.
           Then current().x == 2/60, because v = 1 and it advanced 2 * (1/60).
  Loop b:  frame(0.01) returns 0  (bank = 10 ms, not enough for a dt).
           frame(0.01) returns 1  (bank = 20 ms, one step, 3.33 ms left).
           render_x() == 0.2/60: previous.x = 0, current.x = 1/60, alpha = 0.2.
  Loop c:  frame(5.0) returns <= 15: the clamp to 0.25 s works.

  ======================================================================
  STEPS (the same as the TODOs in the code)
  ======================================================================
  In frame():
    1. Clamp: if frame_time > max_frame, frame_time = max_frame. Use std::min.
    2. Put the time in the bank: accumulator_ += frame_time.
    3. Create a step counter at 0.
    4. while (accumulator_ >= dt), and inside:
         4a. previous_ = current_;    // save the snapshot before moving
         4b. step(current_, dt);      // advance physics one fixed step
         4c. accumulator_ -= dt;      // take that dt out of the bank
         4d. ++steps;
    5. return steps.
  In render_x():
    6. alpha = accumulator_ / dt.
    7. return previous_.x + (current_.x - previous_.x) * alpha.

  WATCH OUT for your previous attempt: you returned  min(max_frame, frame_time) / dt, which only computes
  how many steps WOULD FIT, but doesn't run them (current_ doesn't move) and takes nothing out of the
  bank. The function has to RUN the steps in the while and count them.

  REMEMBER (syntax summary)
    frame_time = std::min(frame_time, max_frame);
    accumulator += frame_time;
    while (accumulator >= dt) { previous = current; step(current, dt); accumulator -= dt; }
    alpha = accumulator / dt;
    render(lerp(previous, current, alpha));   // lerp(a, b, t) = a + (b - a) * t

  INTERVIEW QUESTIONS
  At the end of the file, marked with TODO: QUESTION.
*/
#include <algorithm>   // std::min
#include <cassert>
#include <cmath>
#include <iostream>

// Physics state: position x and constant velocity v (no gravity, it's the bare minimum).
struct State {
    double x = 0.0;
    double v = 1.0;         // 1 unit per second
};

class Loop {
public:
    static constexpr double dt = 1.0 / 60.0;   // FIXED size of each physics step (16.67 ms)
    static constexpr double max_frame = 0.25;  // frame_time cap against the spiral of death

    // Advances a frame that lasted frame_time seconds. Returns how many physics steps it ran.
    int frame(double frame_time) {
        frame_time = std::min(frame_time, max_frame);   // 1. clamp
        accumulator_ += frame_time;                     // 2. all into the bank
        int steps = 0;                                  // 3.
        while (accumulator_ >= dt) {                    // 4. while a step fits
            previous_ = current_;
            step(current_, dt);
            accumulator_ -= dt;
            ++steps;
        }
        return steps;                                   // the leftover stays in accumulator_
    }

    // Position to draw: a point between previous_ and current_.
    double render_x() const {
        double alpha = accumulator_ / dt; //   (0 = draw previous_, 1 = draw current_)
        return previous_.x + (current_.x - previous_.x) * alpha; //  (delete the return 0.0)
    }

    const State& current() const { return current_; }

private:
    static void step(State& s, double h) { s.x += s.v * h; }
    State previous_, current_;
    double accumulator_ = 0.0;
};

int main() {
    Loop a;
    assert(a.frame(1.0 / 30.0) == 2);              // one frame at 30 FPS is 2 steps
    assert(std::abs(a.current().x - 2.0 / 60.0) < 1e-9);

    Loop b;
    assert(b.frame(0.01) == 0);                     // at 100 FPS, sometimes there's no physics
    assert(b.frame(0.01) == 1);
    // 0.02 - 1/60 s left = 20% of a step: draw 20% of the way
    assert(std::abs(b.render_x() - 0.2 / 60.0) < 1e-9);

    Loop c;
    assert(c.frame(5.0) <= 15);                     // a 5 s hitch: capped, not 300 steps
    std::cout << "OK\n";
}

/*
  INTERVIEW QUESTIONS
  Write your answer under each one, in 2-3 sentences, then say it out loud.
  The hint is the minimum that has to come up. Cover it before answering.

  TODO: QUESTION 1. Why is physics with a variable dt neither stable nor deterministic?
  Hint: With a big dt, an object can go through a wall and the integration
    errors grow. With different FPS, the result is different.
  Answer:

  TODO: QUESTION 2. Interpolating adds a frame of latency: why is it worth it?
  Hint: Without interpolation, movement looks jerky when the render FPS doesn't
    match the physics rate. One frame of delay is barely noticeable; the jerkiness is.
  Answer:

  TODO: QUESTION 3. Why steady_clock and not system_clock?
  Hint: system_clock can jump (NTP, time change). steady_clock only moves forward,
    which is what you need to measure intervals.
  Answer:

  TODO: QUESTION 4. How does each engine do it?
  Hint: Unity: FixedUpdate (0.02 s by default, zero or several times per frame).
    Godot: _physics_process at 60 Hz. Unreal: variable tick with substepping or async
    physics, and tick groups (PrePhysics, DuringPhysics, PostPhysics).
  Answer:

  TODO: QUESTION 5. What happens in an Unreal frame, from input until the
    image reaches the screen?
  Hint: Input → game thread ticks by tick group → physics → the render thread
    receives the proxies (one frame behind) → RHI thread → GPU → present.
  Answer:

  TODO: QUESTION 6. Why does rendering run one frame behind and what problems does it bring?
  Hint: That way the game thread and the render work in parallel. Problems: one more frame
    of latency, and you have to copy or duplicate the data (proxies, double buffer) so
    they don't step on each other.
  Answer:

  TODO: QUESTION 7. [Harness] How is an agent loop like a game loop?
  Hint: Tick, state, time budget, actions as commands, and what you do if
    the response doesn't arrive in time. It's the same structure.
  Answer:

  TODO: QUESTION 8. [Design: ML inference in the game] How many ms do you give the model and
    what does the game do if the response hasn't arrived?
  Hint: A fixed budget (for example 1-2 ms, competing with physics and render). The
    inference runs async; if it hasn't arrived, the NPC keeps the last valid
    result. Batching and priority for nearby NPCs.
  Answer:

*/

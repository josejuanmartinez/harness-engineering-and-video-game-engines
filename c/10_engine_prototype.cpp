#include "10_engine_prototype.h"

#include <algorithm>
#include <format>

// ---------------------------------------------------------------- Ball

Ball::Ball(float height) : v2{0.f, height} {}

bool Ball::FixedUpdate(float dt) {
    // Semi-implicit Euler: velocity first, then position with the NEW velocity.
    velocity.y += GRAVITY * dt;
    v2.x += velocity.x * dt;
    v2.y += velocity.y * dt;
    return v2.y > 0.f;
}

// ---------------------------------------------------------------- Engine

Engine::Engine(float dt, std::size_t capacity)
    : dt_(dt),
      capacity_(capacity),
      pool_(std::make_unique<Slot[]>(capacity)),
      randomizer_(std::random_device{}()) {
    for (std::size_t i = 0; i < capacity_; ++i) {        // chain: 0→1→2→…→-1
        pool_[i].next_free = (i + 1 < capacity_) ? int(i + 1) : -1;
    }
    free_head_ = capacity_ > 0 ? 0 : -1;
}

Ball* Engine::SpawnBall(float height) {
    if (free_head_ == -1) return nullptr;                // pool full
    Slot& slot = pool_[free_head_];
    free_head_ = slot.next_free;                         // pop from free list
    slot.alive = true;
    slot.ball = Ball{height};                            // reset to a clean state
    ++alive_count_;
    log("Spawned ball at height", height);
    return &slot.ball;
}

void Engine::DespawnBall(std::size_t i) {
    if (i >= capacity_) return;
    if (!pool_[i].alive) return;                         // double despawn would corrupt the list
    pool_[i].alive = false;
    pool_[i].next_free = free_head_;                     // push onto free list
    free_head_ = int(i);
    --alive_count_;
}

void Engine::Tick() {
    float frameTime = std::min(last_frame_, MAX_FRAME_TIME);
    accumulator_ += frameTime;

    int steps = 0;
    while (accumulator_ >= dt_) {
        for (std::size_t i = 0; i < capacity_; ++i) {
            Slot& slot = pool_[i];
            if (slot.alive && !slot.ball.FixedUpdate(dt_)) {
                log(std::format("  ball #{} hit the ground", i));
                DespawnBall(i);
            }
        }
        accumulator_ -= dt_;
        ++steps;
    }

    std::cout << std::format("frame {:>2} | last frame {:.2f}s (used {:.2f}s) | {:>2} physics steps\n",
                             frame_, last_frame_, frameTime, steps);
    Update(frameTime);
    Render();
    ++frame_;
}

void Engine::Update(float /*frameTime*/) {
    for (std::size_t i = 0; i < capacity_; ++i) {
        if (pool_[i].alive) {
            std::cout << std::format("  ball #{} y = {:7.2f} m\n", i, pool_[i].ball.Position().y);
        }
    }
}

void Engine::Render() {
    // Fake rendering cost: 0.1 .. 1.0 s. The NEXT Tick consumes it.
    std::uniform_int_distribution<int> dist(1, 10);
    last_frame_ = dist(randomizer_) / 10.0f;
}

// ---------------------------------------------------------------- main

int main() {
    Engine engine(1.f / 60.f, 1024);

    engine.SpawnBall(20.f);
    engine.SpawnBall(50.f);
    engine.SpawnBall(100.f);

    constexpr int MAX_FRAMES = 200;                      // safety net
    for (int f = 0; f < MAX_FRAMES && engine.AliveCount() > 0; ++f) {
        engine.Tick();
    }
    log("All balls landed");
}

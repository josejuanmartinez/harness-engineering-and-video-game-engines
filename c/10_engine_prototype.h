#pragma once
// ============================================================================
// 10_engine_prototype.h — mini engine: game loop + fixed timestep + object pool
//
//   Engine::Tick()  (one frame, the "hidden loop" Unity runs for you)
//     1. accumulator_ += last_frame_          time the PREVIOUS frame took
//     2. while (accumulator_ >= dt_)          physics in fixed 1/60 s slices
//            Ball::FixedUpdate(dt_)           -> despawn if it hit the ground
//     3. Update(frameTime)                    gameplay, variable dt (once)
//     4. Render()                             fake cost of this frame -> last_frame_
//
//   Pool: fixed array of Slots allocated once. Free slots form a linked list
//   through their indices (free list), so spawn/despawn are O(1) and balls
//   never move in memory (pointers to them stay valid).
// ============================================================================

#include <cstddef>
#include <iostream>
#include <memory>
#include <random>
#include <string>
#include <type_traits>

// ---------------------------------------------------------------------------
// log("msg") or log("msg", value). Templates must be defined in the header.
// T defaults to nullptr_t so the one-argument call can deduce a type;
// `if constexpr` drops the ": value" part at compile time in that case.
// ---------------------------------------------------------------------------
template<typename T = std::nullptr_t>
void log(const std::string& message, const T& elem = nullptr) {
    std::cout << message;
    if constexpr (!std::is_same_v<T, std::nullptr_t>) std::cout << ": " << elem;
    std::cout << "\n";
}

constexpr float GRAVITY        = -9.8f;  // m/s^2
constexpr float MAX_FRAME_TIME = 0.25f;  // clamp: avoids the "spiral of death"

struct Vector2 {
    float x = 0.f;
    float y = 0.f;
};

class Ball {
public:
    Ball() = default;                    // needed by make_unique<Slot[]>
    explicit Ball(float height);

    bool FixedUpdate(float dt);          // false = hit the ground (dead)
    const Vector2& Position() const { return v2; }

private:
    Vector2 v2{0.f, 1000.f};             // position (m)
    Vector2 velocity{0.f, 0.f};          // m/s
};

struct Slot {
    Ball ball;
    bool alive = false;
    int next_free = -1;                  // next free slot index, -1 = end of list
};

class Engine {
public:
    explicit Engine(float dt, std::size_t capacity);

    Ball* SpawnBall(float height);       // nullptr if the pool is full
    void DespawnBall(std::size_t i);
    void Tick();                         // runs ONE frame
    std::size_t AliveCount() const { return alive_count_; }

private:
    void Update(float frameTime);
    void Render();

    // Declaration order = initialization order (keep in sync with the ctor).
    float dt_;                           // fixed physics step
    std::size_t capacity_;
    std::unique_ptr<Slot[]> pool_;       // freed automatically (RAII)
    std::mt19937 randomizer_;
    int free_head_ = -1;                 // first free slot, -1 = pool full
    std::size_t alive_count_ = 0;
    float accumulator_ = 0.f;
    float last_frame_ = 0.f;             // time the previous frame took
    int frame_ = 0;
};

/*
  04: cache: AoS vs SoA
  Time: 10 min | To measure, compile with -O2 and WITHOUT sanitizers

  THE IDEA
  Memory is slow compared to the CPU, and the CPU doesn't read single bytes: it fetches blocks of
  64 bytes (cache lines). If the data you use is together, each block brings useful
  data. If it's mixed with data you don't use, almost all of it is wasted.
  AoS (array of structs): each particle with all its fields together.
  SoA (struct of arrays): all the x together, all the y together...
  To update positions, SoA reads only what it needs. Here you measure it yourself.

  WHAT THE TESTS CHECK
  - update_aos and update_soa compute the same thing (checks final x and y).
  - The timings and sizeof(ParticleAoS) are the important part. The loop only uses
    16 bytes of each particle. You have to explain why SoA is faster.

  REMEMBER
    The CPU fetches memory in 64-byte lines. If you only use 16 out of every 64,
    you throw away 75% of the bandwidth.
    AoS: vector<Particle>, each particle with all its fields together.
    SoA: one vector per field (x, y, vx, vy...).

  INTERVIEW QUESTIONS
  At the end of the file, marked with TODO: QUESTION.
*/
#include <cassert>
#include <chrono>
#include <cstddef>
#include <iostream>
#include <vector>

struct ParticleAoS {
    float x, y;
    float vx, vy;
    float color[4];
    char name[32];          // "cold" data that update doesn't use
};

struct ParticlesSoA {
    std::vector<float> x, y, vx, vy;
};

void update_aos(std::vector<ParticleAoS>& ps, float dt) {
    // TODO: x += vx * dt; y += vy * dt
}

void update_soa(ParticlesSoA& ps, float dt) {
    // TODO: the same, with one vector per field
}

template <class F>
double ms(F f) {
    auto t0 = std::chrono::steady_clock::now();
    f();
    return std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
}

int main() {
    const std::size_t n = 1'000'000;
    std::vector<ParticleAoS> aos(n);
    ParticlesSoA soa{std::vector<float>(n), std::vector<float>(n),
                     std::vector<float>(n), std::vector<float>(n)};
    for (std::size_t i = 0; i < n; ++i) {
        aos[i].vx = soa.vx[i] = static_cast<float>(i % 10);
        aos[i].vy = soa.vy[i] = 1.0f;
    }

    double t_aos = ms([&] { for (int k = 0; k < 10; ++k) update_aos(aos, 0.5f); });
    double t_soa = ms([&] { for (int k = 0; k < 10; ++k) update_soa(soa, 0.5f); });

    assert(aos[5].x == 25.0f && soa.x[5] == 25.0f);
    assert(aos[n - 1].y == 5.0f && soa.y[n - 1] == 5.0f);
    std::cout << "sizeof(ParticleAoS) = " << sizeof(ParticleAoS) << " bytes; update uses 16\n";
    std::cout << "AoS: " << t_aos << " ms, SoA: " << t_soa << " ms\n";
    std::cout << "OK\n";
}

/*
  INTERVIEW QUESTIONS
  Write your answer under each one, in 2-3 sentences, then say it out loud.
  The hint is the minimum your answer must cover. Cover it before answering.

  TODO: QUESTION 1. [Design: 100k entities] You have 16.6 ms per frame. Do the math
    for the movement system.
  Hint: 1000/60 = 16.6 ms for everything. Movement: 24 bytes per entity × 100k ≈ 2.4
    MB. Contiguous: about 0.1 ms. Scattered (one new per object): 100k cache misses
    × 100 ns ≈ 10 ms. The expensive part is bringing the data from memory.
  Answer:

  TODO: QUESTION 2. Why is SoA faster than AoS in this loop?
  Hint: The CPU loads 64-byte lines. In AoS each line brings fields you don't use.
    In SoA you only bring x and vx, and everything it loads gets used.
  Answer:

  TODO: QUESTION 3. When does AoS win?
  Hint: When you always use all the fields at once: a single cache line
    brings you the whole object.
  Answer:

  TODO: QUESTION 4. Why does SoA make SIMD easier?
  Hint: You have the same data in a row (x0, x1, x2, x3...), so a single
    instruction can process 4 or 8 at once. Unity Burst takes advantage of this.
  Answer:

  TODO: QUESTION 5. [Design: 100k entities] Objects with a virtual update() or an
    ECS? Defend your choice.
  Hint: Virtual: each object in its own place on the heap (cache misses) and an indirect
    call per object. ECS: contiguous components and a system that walks arrays.
    For 100k, ECS.
  Answer:

  TODO: QUESTION 6. What does an ECS gain over GameObjects or Actors? Why did Godot
    decide not to be one?
  Hint: ECS: contiguous data, easy parallelism and composition. Godot prioritizes
    ease of use with nodes, and the heavy work (rendering, physics) is done by the servers with
    compact data.
  Answer:

*/

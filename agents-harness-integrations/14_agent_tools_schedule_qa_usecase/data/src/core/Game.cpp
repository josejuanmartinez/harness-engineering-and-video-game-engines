#include "Game.h"
#include <string>

Game::Game() {
    SaveData data = saves_.load();
    (void)data;

    audio_.loadBank("light_swing", std::vector<std::int16_t>(4096, 100));
    audio_.loadBank("heavy_swing", std::vector<std::int16_t>(4096, 300));

    for (EntityId id = 1; id <= 4; ++id) {
        players_.push_back(std::make_unique<Player>(id, physics_, audio_));
        net_.connect(id, "player" + std::to_string(id));
    }

    physics_.setCollisionCallback([this](RigidBody& a, RigidBody& b) {
        if (a.velocity.y < -20.f) players_[a.owner - 1]->respawn();
        if (b.velocity.y < -20.f) players_[b.owner - 1]->respawn();
    });
}

void Game::tick(float dt) {
    clock_ += dt;
    for (auto& p : players_) {
        p->update(dt);
        p->equipSelected();
        p->attack();
    }
    physics_.step(dt);
    net_.tick(clock_);

    std::int16_t buffer[512];
    audio_.mix(buffer, 512);
}

void Game::run(int frames) {
    for (int i = 0; i < frames; ++i) {
        tick(1.f / 60.f);
    }
}

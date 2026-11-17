#pragma once
#include <memory>
#include <vector>
#include "../audio/AudioMixer.h"
#include "../gameplay/Player.h"
#include "../net/NetSession.h"
#include "../physics/PhysicsWorld.h"
#include "../save/SaveSystem.h"

class Game {
public:
    Game();
    void run(int frames);

private:
    void tick(float dt);

    PhysicsWorld physics_;
    AudioMixer audio_;
    NetSession net_;
    SaveSystem saves_{"savegame.txt"};
    std::vector<std::unique_ptr<Player>> players_;
    float clock_ = 0.f;
};

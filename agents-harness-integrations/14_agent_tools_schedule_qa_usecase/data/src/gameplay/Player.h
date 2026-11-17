#pragma once
#include "Inventory.h"
#include "../core/Types.h"

class RigidBody;
class PhysicsWorld;
class AudioMixer;

class Player {
public:
    Player(EntityId id, PhysicsWorld& world, AudioMixer& audio);

    void update(float dt);
    void selectSlot(int slot) { selectedSlot_ = slot; }
    void equipSelected();
    void attack();
    void respawn();
    float encumbrance() const;

    Inventory& inventory() { return inventory_; }

private:
    EntityId id_;
    PhysicsWorld& world_;
    AudioMixer& audio_;
    Inventory inventory_{8};
    RigidBody* body_ = nullptr;
    const Item* weapon_ = nullptr;
    int selectedSlot_ = 0;
};

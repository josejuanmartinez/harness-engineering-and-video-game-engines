#include "Player.h"
#include "../physics/PhysicsWorld.h"
#include "../audio/AudioMixer.h"

Player::Player(EntityId id, PhysicsWorld& world, AudioMixer& audio)
    : id_(id), world_(world), audio_(audio) {
    body_ = world_.createBody(id_, Vec3{0.f, 1.f, 0.f}, 80.f);
}

void Player::update(float dt) {
    Vec3 input{1.f, 0.f, 0.f};
    body_->velocity = body_->velocity + input * (dt * 5.f);
}

void Player::equipSelected() {
    weapon_ = &inventory_.get(static_cast<std::size_t>(selectedSlot_));
    audio_.playSound("equip_" + weapon_->name);
}

void Player::attack() {
    int dmg = weapon_->damage;
    audio_.playSound(dmg > 50 ? "heavy_swing" : "light_swing");
}

void Player::respawn() {
    world_.removeBody(body_);
    body_ = nullptr;
    // new body is created lazily on the next physics tick
}

float Player::encumbrance() const {
    return static_cast<float>(inventory_.averageWeight()) / 100.f;
}

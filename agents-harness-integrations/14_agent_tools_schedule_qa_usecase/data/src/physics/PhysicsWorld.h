#pragma once
#include <functional>
#include <vector>
#include "../core/Types.h"

class RigidBody {
public:
    EntityId owner = 0;
    Vec3 position;
    Vec3 velocity;
    float mass = 1.f;
    float radius = 0.5f;
};

class PhysicsWorld {
public:
    using CollisionCallback = std::function<void(RigidBody&, RigidBody&)>;

    ~PhysicsWorld();

    RigidBody* createBody(EntityId owner, Vec3 pos, float mass);
    void removeBody(RigidBody* body);
    void setCollisionCallback(CollisionCallback cb) { onCollision_ = std::move(cb); }
    void step(float dt);

private:
    void integrate(float dt);
    void detectCollisions();
    float inverseMass(const RigidBody& b) const;

    std::vector<RigidBody*> bodies_;
    CollisionCallback onCollision_;
};

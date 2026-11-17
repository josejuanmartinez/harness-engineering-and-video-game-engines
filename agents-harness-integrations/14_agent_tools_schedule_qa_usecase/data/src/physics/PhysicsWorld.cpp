#include "PhysicsWorld.h"
#include <algorithm>
#include <cassert>

PhysicsWorld::~PhysicsWorld() {
    for (auto* b : bodies_) delete b;
}

RigidBody* PhysicsWorld::createBody(EntityId owner, Vec3 pos, float mass) {
    auto* b = new RigidBody();
    b->owner = owner;
    b->position = pos;
    b->mass = mass;
    bodies_.push_back(b);
    return b;
}

void PhysicsWorld::removeBody(RigidBody* body) {
    auto it = std::find(bodies_.begin(), bodies_.end(), body);
    if (it != bodies_.end()) {
        bodies_.erase(it);
        delete body;
    }
}

void PhysicsWorld::step(float dt) {
    integrate(dt);
    detectCollisions();
}

float PhysicsWorld::inverseMass(const RigidBody& b) const {
    assert(b.mass > 0.f && "RigidBody mass must be positive");
    return 1.f / b.mass;
}

void PhysicsWorld::integrate(float dt) {
    for (auto* b : bodies_) {
        float invMass = inverseMass(*b);
        b->velocity = b->velocity + Vec3{0.f, -9.81f, 0.f} * (dt * invMass * b->mass);
        b->position = b->position + b->velocity * dt;
    }
}

void PhysicsWorld::detectCollisions() {
    for (auto it = bodies_.begin(); it != bodies_.end(); ++it) {
        for (auto jt = it + 1; jt != bodies_.end(); ++jt) {
            RigidBody& a = **it;
            RigidBody& b = **jt;
            float dx = a.position.x - b.position.x;
            float dy = a.position.y - b.position.y;
            float dz = a.position.z - b.position.z;
            float r = a.radius + b.radius;
            if (dx * dx + dy * dy + dz * dz < r * r && onCollision_) {
                onCollision_(a, b);
            }
        }
    }
}

/*
  REVIEW 05: classes, const and operator overloading
  Level 2 | Time: 15 min

  WHAT IT IS
  A class groups data and invariants (for example, "health never drops below 0").
  - const on a method promises it doesn't modify the object.
  - Overloading operators lets types like Vec2 be used just like numbers.
  - explicit prevents surprise implicit conversions.

  WHAT THE TESTS CHECK
  - Vec2: operators +, *, += and ==. The left-hand * (2.0f * v) is a free
    function. length() is sqrt(x² + y²).
  - Health: that the class keeps its invariant. take_damage and heal clamp to
    the range [0, max] with std::clamp.

  REMEMBER
    class Foo {
    public:
        explicit Foo(int v) : value_(v) {}   // initializer list
        int value() const { return value_; } // const: doesn't modify the object
    private:
        int value_;
    };

    Vec2 operator+(const Vec2& other) const;  // a + b
    bool operator==(const Vec2&) const = default;  // C++20

  THINK
  - What does explicit prevent on a one-argument constructor?
  - struct and class only differ in default visibility.
*/
#include <algorithm>
#include <cassert>
#include <cmath>
#include <iostream>

struct Vec2 {
    float x = 0;
    float y = 0;

    Vec2 operator+(const Vec2& other) const {
        return Vec2{other.x + x, other.y + y};
    }

    Vec2 operator*(float scale) const {
        return Vec2{x * scale, y * scale};
    }

    Vec2& operator+=(const Vec2& other) {
        x += other.x;
        y += other.y;
        return *this;
    }

    float length() const {
        return std::sqrt(x*x + y*y);
    }

    bool operator==(const Vec2&) const = default;
};

// Lets you write 2.0f * v as well as v * 2.0f.
Vec2 operator*(float scale, const Vec2& v) {
    return Vec2{v.x * scale, v.y * scale};
}

class Health {
    public:
        explicit Health(int max) : max_(max), current_(max) {}

        int current() const { return current_; }
        bool is_alive() const {
            return this->current_ > 0;
        }

        // Subtracts health without going below 0.
        void take_damage(int amount) {
            this->current_ = std::clamp(this->current_ - amount, 0, max_);
        }

        // Adds health without exceeding max_.
        void heal(int amount) {
            this->current_ = std::clamp(this->current_ + amount, 0, max_);
        }

    private:
        int max_;
        int current_;
    };

int main() {
    Vec2 a{1, 2};
    Vec2 b{3, 4};
    assert((a + b == Vec2{4, 6}));
    assert((a * 2.0f == Vec2{2, 4}));
    assert((2.0f * a == Vec2{2, 4}));
    assert(b.length() == 5.0f);

    a += b;
    assert((a == Vec2{4, 6}));

    Health health(100);
    assert(health.is_alive());
    health.take_damage(30);
    assert(health.current() == 70);
    health.heal(50);
    assert(health.current() == 100);
    health.take_damage(500);
    assert(health.current() == 0 && !health.is_alive());

    std::cout << "OK\n";
}

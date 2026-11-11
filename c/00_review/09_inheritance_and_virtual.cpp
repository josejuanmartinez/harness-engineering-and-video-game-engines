/*
  REVIEW 09: inheritance, virtual and polymorphism
  Level 2 | Time: 15 min

  WHAT IT IS
  Dynamic polymorphism: you call a method through a Base* or Base&, and at
  runtime the version of the real class runs. It works through the vtable: each
  object stores a hidden pointer to a table of functions for its class.

  WHAT THE TESTS CHECK
  - override of area() and name(): through unique_ptr<Shape> the Rect and Square
    versions get called.
  - Base constructor: Square passes side to Rect(side, side).
  - Virtual destructor: live goes back to 0 when the Shape vector is destroyed. Without virtual
    on ~Shape the derived class destructor wouldn't be called.
  - Slicing: copying a Square into a Rect by value loses the Square part, and
    name() starts returning "rect". With a reference it doesn't happen.

  REMEMBER
    class Base {
    public:
        virtual ~Base() = default;        // Essential if you delete through Base*
        virtual float area() const = 0;   // Pure: derived classes must implement it
    };
    class Derived : public Base {
    public:
        float area() const override;      // override catches signature mistakes
    };

  THINK
  - How does a vtable work? How much does a virtual call cost?
  - What is object slicing? Look at the test at the end
  - Why do engines avoid virtual in loops over thousands of objects?
*/
#include <cassert>
#include <iostream>
#include <memory>
#include <string>
#include <utility>
#include <vector>

class Shape {
    public:
        inline static int live = 0;
        explicit Shape(float area): area_(area) { this->live++;};

        virtual float area() { return this->area_;}
        virtual std::string name() { return this->name_;}

        ~Shape() {
            this->live--;
        }

    private:
        float area_ = 0;
        std::string name_ = "shape";
};

class Rect : public Shape {
    public:
        explicit Rect(float w, float h): Shape(w*h), w_(w), h_(h) {};

        std::string name() override {
            return "rect";
        }
    private:
        float w_;
        float h_;
};

class Square : public Rect {
    public:
        explicit Square(float side) : Rect(side, side) {};
        std::string name() override {
            return "square";
        }
};

// Sums the areas of all the shapes.
float total_area(const std::vector<std::unique_ptr<Shape>>& shapes) {
    float res = 0.0;
    for(auto& elem: shapes) {
        res += elem.get()->area();
    }
    return res;
}

int main() {
    {
        std::vector<std::unique_ptr<Shape>> shapes;
        shapes.push_back(std::make_unique<Rect>(2.0f, 3.0f));
        shapes.push_back(std::make_unique<Square>(2.0f));

        assert(shapes[0]->name() == "rect");
        assert(shapes[1]->name() == "square");
        assert(total_area(shapes) == 10.0f);
        assert(Shape::live == 2);
    }
    assert(Shape::live == 0);

    // Slicing: copying into a Rect loses the Square part.
    Square square(2.0f);
    Rect sliced = square;
    assert(sliced.name() == "rect");

    Rect& ref = square;
    assert(ref.name() == "square");

    std::cout << "OK\n";
}

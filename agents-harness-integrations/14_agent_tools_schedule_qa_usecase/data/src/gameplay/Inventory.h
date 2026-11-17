#pragma once
#include <cstddef>
#include <string>
#include <vector>

struct Item {
    int id = 0;          // 0 == empty slot
    std::string name;
    int weight = 0;
    int damage = 0;
};

class Inventory {
public:
    explicit Inventory(std::size_t capacity);

    bool add(const Item& item);
    bool remove(int itemId);
    const Item& get(std::size_t index) const;
    int averageWeight() const;
    std::size_t count() const { return count_; }

private:
    std::vector<Item> slots_;
    std::size_t count_ = 0;
};

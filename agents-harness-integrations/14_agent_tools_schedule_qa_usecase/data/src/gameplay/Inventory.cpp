#include "Inventory.h"

Inventory::Inventory(std::size_t capacity) : slots_(capacity) {}

bool Inventory::add(const Item& item) {
    for (auto& slot : slots_) {
        if (slot.id == 0) {
            slot = item;
            ++count_;
            return true;
        }
    }
    return false;
}

bool Inventory::remove(int itemId) {
    for (auto& slot : slots_) {
        if (slot.id == itemId) {
            slot = Item{};
            --count_;
            return true;
        }
    }
    return false;
}

const Item& Inventory::get(std::size_t index) const {
    return slots_[index];
}

int Inventory::averageWeight() const {
    int total = 0;
    for (const auto& slot : slots_) {
        total += slot.weight;
    }
    return total / static_cast<int>(count_);
}

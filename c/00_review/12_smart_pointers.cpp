/*
  REVIEW 12: unique_ptr, shared_ptr and weak_ptr
  Level 3 | Time: 20 min
  Prepares you for: ../03_handles.cpp and ../08_scene_tree.cpp

  WHAT IT IS
  The problem: with new, YOU have to call delete once and on every path
  (early return, exceptions). If you forget, there's a leak; if you do it twice,
  a crash.

  unique_ptr is a class that holds a pointer and calls delete on its own in its
  destructor. It's RAII (06) applied to a new:
      auto e = std::make_unique<Enemy>(args);   // does the new
      e->hp = 10;                               // used like a pointer
      Enemy* raw = e.get();                     // raw pointer to read, without giving up ownership
  }   // on leaving scope it calls delete on its own

  "Unique" = a single owner. Copying it is forbidden: there would be two deletes, as in 07.
  Moving it is allowed: the new one is the owner and the old one is left as nullptr, as
  in 08.
      auto b = a;              // doesn't compile
      auto b = std::move(a);   // ok: now a is empty

  Smart pointers are RAII applied to dynamic memory. They make explicit who
  owns what:
  - unique_ptr: a single owner, zero cost, moves but doesn't copy.
  - shared_ptr: several owners with a reference count. It's freed when the
    last one dies.
  - weak_ptr: observes a shared_ptr without keeping it alive. Breaks cycles.

  WHAT THE TESTS CHECK
  - LinkedList: chained ownership with unique_ptr. Each node owns the next one.
    Inserting and removing require std::move. To traverse, a raw Node* is enough, which
    isn't an owner. pop_front on empty doesn't break.
  - TreeNode: parents own their children (shared_ptr) and the child observes the parent
    (weak_ptr). use_count confirms there's no cycle: when root dies, the child's weak_ptr
    expires and lock() returns empty.

  REMEMBER
    auto p = std::make_unique<Foo>(args);   // A single owner. Moves, doesn't copy
    auto s = std::make_shared<Foo>(args);   // Several owners, with refcount
    std::weak_ptr<Foo> w = s;               // Observes without owning
    if (auto locked = w.lock()) { ... }     // shared_ptr, or empty if it already died
    s.use_count();

  Two objects pointing at each other with shared_ptr are never destroyed: it's a cycle.
  That's why the child holds its parent with weak_ptr.
*/
#include <algorithm>
#include <cassert>
#include <cstddef>
#include <iostream>
#include <memory>
#include <string>
#include <utility>
#include <vector>

// Linked list: each node owns the next one.
class LinkedList {
public:
    void push_front(int value) {
        Node n{.value = value, .next = std::move(this->head_)};
        this->head_ = std::make_unique<Node>(std::move(n));
        ++size_;
    }

    // Removes the first one. Does nothing if it's empty.
    void pop_front() {
        if (size_ < 1 || this->head_ == nullptr) return;
        this->head_ = std::move(this->head_->next);
        --size_;
    }

    bool contains(int value) const {
        if (this->size_ < 1 || !head_) return false;
        auto elem = this->head_.get();
        while(true) {
            if(elem->value == value) return true;
            if(!elem->next) break;
            elem = elem->next.get();
        }
        return false;
    }

    std::size_t size() const { return size_; }

private:
    struct Node {
        int value = 0;
        std::unique_ptr<Node> next;
    };

    std::unique_ptr<Node> head_;
    std::size_t size_ = 0;
};

// Tree: parents own their children and children observe their parent.
struct TreeNode {
    std::string name;
    std::weak_ptr<TreeNode> parent;
    std::vector<std::shared_ptr<TreeNode>> children;
};

std::shared_ptr<TreeNode> make_node(std::string name) {
    auto node = std::make_shared<TreeNode>();
    node->name = std::move(name);
    return node;
}

void add_child(const std::shared_ptr<TreeNode>& parent,
               const std::shared_ptr<TreeNode>& child) {
    (void)parent;
    (void)child;  // TODO
}

// Returns the parent's name, or "" if it has none or it no longer exists.
std::string parent_name(const std::shared_ptr<TreeNode>& node) {
    (void)node;
    return "";  // TODO: use lock()
}

int main() {
    LinkedList list;
    list.push_front(1);
    list.push_front(2);
    assert(list.size() == 2);
    assert(list.contains(1));
    assert(!list.contains(3));
    list.pop_front();
    assert(list.size() == 1);
    assert(!list.contains(2));
    list.pop_front();
    list.pop_front();
    assert(list.size() == 0);

    auto child = make_node("child");
    {
        auto root = make_node("root");
        add_child(root, child);
        assert(parent_name(child) == "root");
        assert(child.use_count() == 2);  // child and root->children
    }
    // root no longer exists: weak_ptr didn't keep it alive.
    assert(parent_name(child) == "");
    assert(child.use_count() == 1);

    std::cout << "OK\n";
}

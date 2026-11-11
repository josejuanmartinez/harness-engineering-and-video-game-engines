/*
  08: scene tree (Godot / Unity style)
  Time: 15 min

  THE IDEA
  In Godot and in Unity, the game is a tree of objects (nodes or GameObjects). The engine
  notifies them at specific moments: when entering the scene, when they are ready and every frame.
  Order matters: in Godot, ready reaches the children first, so the parent can use them
  already initialized.
  Also, deleting is not immediate. If a node were deleted while the engine walks the tree,
  the walk would use freed memory. That's why queue_free and Destroy only mark the node, and
  the real deletion happens at the end of the frame.

  WHAT THE TESTS CHECK
  - start: enter goes top-down (parent before children) and ready goes bottom-up
    (children before parent), like in Godot.
  - frame: process walks the tree in order. Bomb marks B for deletion
    (queue_free) and B is no longer processed in that frame.
  - Deferred deletion: marked nodes are deleted at the end of the frame, not during
    the walk. In frame 2, bomb and B no longer exist, and ASan would warn if they
    were touched.

  REMEMBER
    Godot: on entering the scene, _enter_tree goes top-down through the whole subtree;
    then _ready goes bottom-up (the children are ready before the parent).
    Then, every frame, _process in tree order.
    queue_free() doesn't delete right away: it marks the node and it's deleted at the end of the frame.
    Unity does the same with Destroy().

  INTERVIEW QUESTIONS
  At the end of the file, marked with TODO: QUESTION.
*/
#include <cassert>
#include <iostream>
#include <memory>
#include <string>
#include <vector>
#include <iostream>
#include <format>

std::vector<std::string> log_;      // records the order of the calls

class Node {
public:
    explicit Node(std::string name) : name_(std::move(name)) {}
    virtual ~Node() = default;

    Node* add_child(std::unique_ptr<Node> child) {
        child->parent_ = this;
        children_.push_back(std::move(child));
        return children_.back().get();
    }

    // Called by the tree when putting this node (with its children) into the scene.
    void propagate_enter() {
        enter_rec();
        ready_rec();
    }

    void propagate_process(float dt) {
        // TODO: if this node is marked, do nothing (neither it nor its children).
        if(this->queued_) return;
        process(dt);
        //       Otherwise: process(dt) and then the children. Walk by index
        for(std::size_t i = 0; i<this->children_.size(); ++i) {
          this->children_[i]->propagate_process(dt);
        }
    }

    // End of the frame: deletes the marked children (with their subtree), recursively.
    void flush_freed() {
        for (auto& c : children_) c->flush_freed();
        std::erase_if(this->children_, [](const std::unique_ptr<Node>& x){return x->queued_;});
    }

    void queue_free() { queued_ = true; }
    const std::string& name() const { return name_; }
    Node* parent() const { return parent_; }

protected:
    virtual void process(float) { log_.push_back("process:" + name_); }

private:
    std::string name_;
    Node* parent_ = nullptr;
    std::vector<std::unique_ptr<Node>> children_;
    bool queued_ = false;

    void enter_rec() {
        log_.push_back("enter:" + name_);          // me, then children (pre-order)
        for (auto& c : children_) c->enter_rec();
    }
    void ready_rec() {
        for (auto& c : children_) c->ready_rec();  // children, then me (post-order)
        log_.push_back("ready:" + name_);
    }
};

// A node that, when processed, frees itself and a sibling.
class Bomb : public Node {
public:
    using Node::Node;
    Node* victim = nullptr;

protected:
    void process(float dt) override {
        Node::process(dt);
        queue_free();
        if (victim) victim->queue_free();
    }
};

class Tree {
public:
    Node* root() { return root_.get(); }
    void start() { root_->propagate_enter(); }
    void frame(float dt) {
        root_->propagate_process(dt);
        root_->flush_freed();           // end of the frame: now it really is deleted
    }

private:
    std::unique_ptr<Node> root_ = std::make_unique<Node>("root");
};

int main() {
    Tree tree;
    Node* a = tree.root()->add_child(std::make_unique<Node>("A"));
    a->add_child(std::make_unique<Node>("A1"));
    auto* bomb = static_cast<Bomb*>(tree.root()->add_child(std::make_unique<Bomb>("bomb")));
    Node* b = tree.root()->add_child(std::make_unique<Node>("B"));
    bomb->victim = b;

    tree.start();
    std::vector<std::string> expected_start = {
        "enter:root", "enter:A", "enter:A1", "enter:bomb", "enter:B",
        "ready:A1", "ready:A", "ready:bomb", "ready:B", "ready:root"};
    assert(log_ == expected_start);

    log_.clear();
    tree.frame(0.016f);
    // bomb marks B before its turn, and in this exercise a marked node
    // is no longer processed
    std::vector<std::string> expected_frame1 = {"process:root", "process:A", "process:A1", "process:bomb"};
    assert(log_ == expected_frame1);

    log_.clear();
    tree.frame(0.016f);
    std::vector<std::string> expected_frame2 = {"process:root", "process:A", "process:A1"};
    assert(log_ == expected_frame2);    // bomb and B no longer exist; ASan would warn if they were used
    std::cout << "OK\n";
}

/*
  INTERVIEW QUESTIONS
  Write your answer under each one, in 2-3 sentences, then say it out loud.
  The hint is the minimum that has to come up. Cover it before answering.

  TODO: QUESTION 1. Why does ready go bottom-up? What can the parent take
    for granted?
  Hint: The children are already ready when ready reaches the parent, so the parent
    can use and configure them.
  Answer:

  TODO: QUESTION 2. Why does Unity defer Destroy and Godot defer queue_free?
  Hint: If it were deleted right away, the engine (or your own code) could still be
    walking or using the object this frame: freed memory. It's marked and
    deleted at the end of the frame.
  Answer:

  TODO: QUESTION 3. What is the order of the Unity lifecycle?
  Hint: Awake → OnEnable → Start (before the first Update) → FixedUpdate (0 or several
    per frame) → Update → LateUpdate → OnDisable → OnDestroy.
  Answer:

  TODO: QUESTION 4. [Godot] How does it manage memory without a GC?
  Hint: RefCounted (the Resources) is freed by refcount (Ref<T> in C++). Nodes
    are freed by hand with queue_free. Everything is registered in ClassDB, which is its
    reflection.
  Answer:

  TODO: QUESTION 5. [Unreal] How does its GC work?
  Hint: Mark & sweep from a root set, following UPROPERTY references. To avoid
    causing spikes it uses incremental purge and clustering. What isn't a UObject uses
    TSharedPtr and TUniquePtr.
  Answer:

  TODO: QUESTION 6. [Unreal] What are Actor, Component, GameMode and Pawn?
  Hint: AActor contains UActorComponents; USceneComponents have a transform and
    hierarchy. GameMode only exists on the server. Pawn is what a
    PlayerController controls.
  Answer:

  TODO: QUESTION 7. A tree of pointers is bad for the cache. How does Godot
    solve it?
  Hint: Nodes are just the facade. The heavy work is done by the servers
    (RenderingServer, PhysicsServer) with their own compact data and RIDs.
  Answer:

  TODO: QUESTION 8. [Unity] What is IL2CPP and why does it exist?
  Hint: It converts C# IL to C++ and compiles it ahead of time (AOT). It's required
    on iOS and consoles, where JIT isn't allowed, and is usually faster than Mono.
  Answer:

  TODO: QUESTION 9. [Design: game and render thread] What happens if you destroy an object
    that the render is still drawing?
  Hint: The render reads from a copy (proxy), not from the object. Destroying the proxy
    is queued for the render thread, so it's deleted when the render no longer uses it.
  Answer:

*/

/*
  TODO: HANDS-ON (optional, 30 min). Godot 4, so you can say "I've used it"
  1. Download Godot 4 (standard) from godotengine.org. It needs no install. If
     Windows blocks the .exe, use the Linux version in WSL.
  2. Create a scene: a root Node2D with two children, each with a script that
     prints in _enter_tree, _ready and _process. Look at the order in the console: it's the
     same as in this exercise's tests.
  3. Connect a signal between two nodes. Then queue_free() the receiver and emit
     again: it doesn't crash, because the connection is removed on its own (exercise 06).
  4. Optional: move a CharacterBody2D with _physics_process and the keyboard.
  5. Optional: on GitHub, open scene/main/node.cpp (_propagate_ready) and
     core/templates/rid_owner.h. It's the real code for what you did in 08 and 03.
  In the interview, be honest: "I've made prototypes in Godot and I know the
  architecture of Unreal and Unity". Don't say you've worked with them in production.
*/

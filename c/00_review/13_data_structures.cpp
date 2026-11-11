/*
  REVIEW 13: data structures, overview
  Level 3 | Time: 10 min | Each TODO is a single line
  Prepares you for: ../04_cache_aos_soa.cpp and ../05_sparse_set.cpp

  WHAT IT IS
  Each structure stores data in memory in a different way. That layout
  decides which operations are fast. In an engine one thing matters most:
  whether the data is TOGETHER (contiguous) or SCATTERED (nodes with pointers).
  Walking contiguous memory is much faster because the CPU loads it into the cache
  64 bytes at a time.

  Structure            In memory              Access    Insert/remove       In an engine
  -------------------  ---------------------  --------  ------------------  ---------------------------
  T[N], std::array     contiguous, fixed      O(1)      size doesn't change fixed-size data
  std::vector          contiguous, grows x2   O(1)      O(1) at the end     THE default choice
                                                        O(n) in the middle
  std::deque           contiguous blocks      O(1)      O(1) at the ends    work queues
  std::list            loose nodes            O(n)      O(1) if you have    almost never: cache misses
                                                        the node
  std::unordered_map   hash table (buckets)   O(1) avg  O(1) avg            look up by id or name
  std::map / set       red-black tree         O(log n)  O(log n)            if you need ordering
  std::priority_queue  heap over a vector     top O(1)  O(log n)            A*, timed events
  stack / queue        adapters (deque)       ends      O(1)                undo, BFS

  What you need to be able to say out loud:
  - vector by default. Even where theory says list, vector usually wins
    because it's contiguous.
  - Removing from the middle of a vector when order doesn't matter: swap-and-pop. You swap the
    element with the last one and do pop_back. It's O(1) and it's what an ECS does (05).
  - push_back can reallocate, and then every pointer and iterator into the
    vector stops being valid. That's why engines use handles (03) and not pointers.
  - unordered_map is O(1) on average, but each node is loose on the heap. For
    few elements, a vector walked linearly can be faster.

  WHAT THE TESTS CHECK
  Each TODO is a single line: declare a container or call a method. The idea
  is that you touch each structure once.
  - array: declare a fixed-size one, zeroed.
  - vector: push_back, and remove with swap-and-pop (std::swap + pop_back).
  - deque: push at both ends.
  - list: insert in the middle with an iterator.
  - unordered_map: declare it and ask whether a key exists.
  - map: check that it's sorted.
  - priority_queue: declare it so it gives the smallest, read the top one and remove it.
  Until you do the declaration TODOs, the file doesn't compile: that's expected.

  REMEMBER
    std::array<int, 4> a{};                 // fixed size, all 0
    v.push_back(x);  v.pop_back();  v.back();
    std::swap(x, y);
    d.push_front(x);  d.push_back(x);
    l.insert(iterator, value);              // inserts BEFORE the iterator
    std::unordered_map<Key, Value> m;   m.contains(key);
    m.begin()->first                        // key of the first element
    std::priority_queue<int, std::vector<int>, std::greater<int>> q;   // gives the smallest
    q.push(x);  q.top();  q.pop();

  THINK
  - Why is a list of 1000 elements slower to walk than a vector of 1000?
  - You have 10,000 enemies and look one up by id every frame: which structure do you use?
  - What happens to a pointer to v[0] if you do v.push_back() and the vector grows?
*/
#include <array>
#include <cassert>
#include <deque>
#include <iostream>
#include <list>
#include <map>
#include <queue>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

int main() {
    // array
    // TODO: declare grid: a std::array of 4 ints, all 0
    std::array<int, 4> grid{0,0,0,0};
    assert(grid.size() == 4 && grid[3] == 0);

    // vector
    std::vector<int> v{10, 20, 30, 40};
    v.push_back(50);
    assert(v.size() == 5 && v.back() == 50);

    // Swap-and-pop: removes the 20 (index 1) in O(1) without keeping the order.
    // TODO: swap v[1] with the last element
    std::swap(v[1], v[v.size()-1]);
    // TODO: remove the last element
    v.pop_back();
    assert((v == std::vector<int>{10, 50, 30, 40}));


    // deque
    std::deque<int> d{2, 3};
    // TODO: push 1 at the front
    d.push_front(1);
    // TODO: push 4 at the back
    d.push_back(4);
    assert(d.size() == 4 && d.front() == 1 && d.back() == 4);


    // list
    std::list<int> l{1, 3};
    auto it = std::next(l.begin());  // points to the 3
    // TODO: insert 2 before it
    l.insert(it, 2);
    assert((l == std::list<int>{1, 2, 3}));


    // unordered_map
    // TODO: declare by_id: a std::unordered_map from int to std::string
    std::unordered_map<int, std::string> by_id{};
    by_id[7] = "orc";
    by_id[3] = "elf";
    assert(by_id.at(7) == "orc");
    bool has_99 = by_id.contains(99);
    assert(!has_99);


    // map
    std::map<int, std::string> sorted{{7, "orc"}, {3, "elf"}, {5, "troll"}};
    int first_key = sorted.begin()->first;
    assert(first_key == 3);  // the map keeps its keys sorted

    // priority_queue. Typical use: the next event to run, or the next A* node.
    std::priority_queue<int, std::vector<int>, std::greater<int>> next_event{};
    next_event.push(30);
    next_event.push(10);
    next_event.push(20);
    int first_event = next_event.top();
    assert(first_event == 10);
    next_event.pop();
    assert(next_event.top() == 20);

    std::cout << "OK\n";
}

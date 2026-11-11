/*
  REVIEW 04: map, set, sort and pair
  Level 1 | Time: 20 min

  WHAT IT IS
  The STL associative containers:
  - unordered_map / unordered_set: hash table, O(1) lookup on average.
  - map / set: ordered tree, O(log n).
  sort with a comparator lets you order by any criterion. It's the basis of caches,
  indices and counts.

  WHAT THE TESTS CHECK
  - word_freq: count with unordered_map (m[key]++ creates the key at 0).
  - top_k: sort by two criteria: descending frequency and then name.
  - has_duplicates: detect repeats. With an unordered_set it's O(n) instead of O(n²).
  - sort_by_score: std::sort with a lambda as the comparator.

  REMEMBER
    std::unordered_map<std::string, int> m;
    m["a"]++;                          // creates the key with 0 if it doesn't exist
    for (const auto& [key, value] : m) { ... }  // structured bindings
    m.contains("a");                   // C++20
    std::unordered_set<int> seen;
    auto [it, inserted] = seen.insert(5);  // inserted is false if it was already there
    std::sort(v.begin(), v.end(), [](const T& a, const T& b) { return a.x < b.x; });

  THINK
  - When would you use std::map instead of std::unordered_map?
  - The sort comparator must return false for equal elements. Why?
*/
#include <algorithm>
#include <cassert>
#include <iostream>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

struct Player {
    std::string name;
    int score;
};

// Counts how many times each word appears.
std::unordered_map<std::string, int> word_freq(const std::vector<std::string>& words) {
    std::unordered_map<std::string, int> results{};
    for(auto value: words) {
        if (results.contains(value)) {
            results[value]++;
        } else {
            results[value] = 1;
        }
    }
    return results;
}

// Returns the k most frequent words. On a tie, in alphabetical order.
std::vector<std::pair<std::string, int>> top_k(
    const std::unordered_map<std::string, int>& freq, std::size_t k) {
    std::vector<std::pair<std::string, int>> mostFrequent{};

    std::vector<int> frequencies{};
    for(auto [key, value]: freq) {
        // std::cout << key << " " << value << "\n";
        auto it = std::find(frequencies.begin(), frequencies.end(), value);
        if(it == frequencies.end()) {
            frequencies.push_back(value);
        }
    }
    std::sort(frequencies.begin(), frequencies.end(), [](int a, int b) {return a > b;});
    for(auto frequency: frequencies) {
        std::cout << frequency << "\n";
        std::vector<std::string> candidates{};
        for(auto [key, value]: freq) {
            if (value == frequency) {
                candidates.push_back(key);
                std::cout << "Pushed " << key << "\n";
            }
        }
        std::sort(candidates.begin(), candidates.end());
        for(auto candidate: candidates) {
            mostFrequent.push_back({candidate,frequency});
            std::cout << "size " << mostFrequent.size() << "\n";
            if(mostFrequent.size() >= k) break;
        }
        if(mostFrequent.size() >= k) break;
    }
    return mostFrequent;
}

// true if some number appears more than once.
bool has_duplicates(const std::vector<int>& values) {
    for(auto it = values.begin(); it < values.end(); it++) {
        for(auto it2 = it+1; it2 < values.end(); it2++) {
            if (*it == *it2) return true;
        }
    }

    return false;
}

// Sorts from highest to lowest score.
void sort_by_score(std::vector<Player>& players) {
    std::sort(players.begin(), players.end(), [](Player p1, Player p2) {
        return p1.score > p2.score;
    });
}

int main() {
    auto freq = word_freq({"goal", "foul", "goal", "corner", "foul", "goal"});
    assert(freq["goal"] == 3);
    assert(freq["corner"] == 1);

    auto top = top_k({{"b", 2}, {"a", 2}, {"c", 5}, {"d", 1}}, 3);
    assert(top.size() == 3);
    assert(top[0].first == "c");
    assert(top[1].first == "a");
    assert(top[2].first == "b");

    assert(has_duplicates({1, 2, 1}));
    assert(!has_duplicates({1, 2, 3}));

    std::vector<Player> players{{"Ana", 10}, {"Leo", 30}, {"Eva", 20}};
    sort_by_score(players);
    assert(players[0].name == "Leo" && players[2].name == "Ana");

    std::cout << "OK\n";
}

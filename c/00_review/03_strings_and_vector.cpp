/*
  REVIEW 03: std::string and std::vector
  Level 1 | Time: 15 min

  WHAT IT IS
  std::string and std::vector are dynamic arrays: they grow on their own and free their memory
  when destroyed. They're the containers you'll use most. You need to know their API and
  the edge cases (empty, a single element, unsigned indices).

  WHAT THE TESTS CHECK
  - is_palindrome: index a string, also empty and one letter long.
  - split: substr and find, including empty fields ("a,,b") and no separator at all.
  - reverse_words: combine split with std::reverse and join again.
  - remove_evens: remove elements with std::erase_if instead of doing it by hand.

  REMEMBER
    std::vector<int> v{1, 2};
    v.push_back(3);  v.size();  v.back();  v.empty();
    std::string s = "hello";
    s.substr(pos, count);  s.find(',');  s += "x";  s.size();
    #include <algorithm>
    std::erase_if(v, [](int x) { return x % 2 == 0; });  // C++20, in <vector>

  THINK
  - Why is s.size() - 1 dangerous if s is empty?
    (hint: size() is unsigned)
*/
#include <algorithm>
#include <cassert>
#include <iostream>
#include <string>
#include <vector>

// true if text reads the same both ways.
bool is_palindrome(const std::string& text) {
    short text_size = text.size();
    short max_pos = (short) text_size / 2;
    for(auto i = 0; i<max_pos;i++) {
        short reverse = text_size - i - 1 ;
        if(text[i] != text[reverse]) return false;
    }
    return true;
}

// Splits text by the separator. split("a,b", ',') returns {"a", "b"}.
std::vector<std::string> split(const std::string& text, char separator) {
    std::vector<std::string> result{};
    size_t start = 0;
    while(start < text.size()) {
        std::string partial = text.substr(start, text.size());
        size_t match = partial.find(separator);
        if (match != std::string::npos) {
            std::string topush = text.substr(start, match);
            result.push_back(topush);
            start += match + 1;
        }
        else {
            result.push_back(partial);
            break;
        }
    }

    return result;
}

// reverse_words("hello big world") returns "world big hello".
std::string reverse_words(const std::string& text) {
    std::vector<std::string> tokens{};
    std::string result = "";

    size_t start = 0;
    while(start < text.size()) {
        std::string partial = text.substr(start, text.size());
        size_t match = partial.find(" ");
        if(match != std::string::npos) {
            std::string candidate = text.substr(start, match);
            tokens.push_back(candidate);
            start += match+1;
        }
        else {
            tokens.push_back(partial);
            break;
        }
    }
    std::reverse(tokens.begin(), tokens.end());

    for(std::string elem: tokens) {
        if(result.size() > 0) result.append(" ");
        result.append(elem);
    }
    return result;  // TODO: you can reuse split
}

// Removes all even numbers from the vector.
void remove_evens(std::vector<int>& values) {
    std::erase_if(values, [](int x) {return x % 2 == 0;});
}

int main() {
    assert(is_palindrome("racecar"));
    assert(is_palindrome(""));
    assert(is_palindrome("a"));
    assert(!is_palindrome("hello"));

    assert((split("a,b,c", ',') == std::vector<std::string>{"a", "b", "c"}));
    assert((split("a,,b", ',') == std::vector<std::string>{"a", "", "b"}));
    assert((split("alone", ',') == std::vector<std::string>{"alone"}));

    assert(reverse_words("hello big world") == "world big hello");

    std::vector<int> v{1, 2, 3, 4, 5};
    remove_evens(v);
    assert((v == std::vector<int>{1, 3, 5}));

    std::cout << "OK\n";
}

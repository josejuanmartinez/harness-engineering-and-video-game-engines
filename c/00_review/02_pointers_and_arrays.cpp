/*
  REVIEW 02: pointers and arrays
  Level 1 | Time: 15 min

  WHAT IT IS
  A pointer is a variable that holds a memory address. An array in C is
  a contiguous block of memory, and its name converts to a pointer to the first
  element. Engines work mostly with this: buffers, ranges and iterators.

  WHAT THE TESTS CHECK
  - sum_array: walk memory with pointer arithmetic. With n = 0 it reads nothing.
  - reverse_array: two pointers moving toward the middle, with even, odd
    and 0 size. With n = 0, data + (n - 1) goes outside the array.
  - find_value: the [begin, end) range convention and returning nullptr if it
    doesn't find it.

  REMEMBER
    int x = 5;
    int* p = &x;     // p holds the address of x
    *p = 7;          // changes x through the pointer
    int arr[3] = {1, 2, 3};
    int* q = arr;    // an array decays to a pointer to its first element
    *(q + 1);        // same as q[1]
    int* none = nullptr;

  A range [begin, end) includes begin, but end points just past the last one.

  THINK
  - What's the difference between const int* p and int* const p?
  - Why must you never read *end?
*/
#include <cassert>
#include <cstddef>
#include <iostream>

// Sums n elements using the pointer.
int sum_array(const int* data, std::size_t n) {
    int sum = 0;
    const int* q = data;
    for(size_t i = 0; i < n; i++) {
        if (q != nullptr) {
            sum += *(q+i);
        }
    }
    return sum;
}

// Reverses the array in place with two pointers moving toward each other.
void reverse_array(int* data, std::size_t n) {
    int* pointer1 = data;
    int* pointer2 = data+(n-1);
    while(pointer1 < pointer2) {

        int temp = *pointer2;
        *pointer2 = *pointer1;
        *pointer1 = temp;

        pointer1++;
        pointer2--;
    }
}

// Searches for value in [begin, end). Returns a pointer to the element or nullptr.
const int* find_value(const int* begin, const int* end, int value) {
    for(const int* i = begin; i< end; i++) {
        if( *i == value) return i;
    }
    return nullptr;
}

int main() {
    int a[] = {1, 2, 3, 4};
    assert(sum_array(a, 4) == 10);
    assert(sum_array(a, 0) == 0);

    reverse_array(a, 4);
    assert(a[0] == 4 && a[1] == 3 && a[2] == 2 && a[3] == 1);

    int odd[] = {1, 2, 3};
    reverse_array(odd, 3);
    assert(odd[0] == 3 && odd[1] == 2 && odd[2] == 1);
    reverse_array(odd, 0);

    const int* found = find_value(a, a + 4, 3);
    assert(found == a + 1);
    assert(find_value(a, a + 4, 99) == nullptr);

    std::cout << "OK\n";
}

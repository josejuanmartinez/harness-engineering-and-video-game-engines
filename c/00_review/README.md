# C++ review: from simple to complex

Do this folder before the exercises in `c/`. Each level prepares the next one, and the last one leads straight into the interview.

## How it works

1. Open an exercise and read the header:
   - `WHAT IT IS` explains the concept and why it matters.
   - `WHAT THE TESTS CHECK` says what each test checks.
   - `REMEMBER` gives you the syntax you need.
2. Fill in the `TODO`s. The tests are already written in `main`.
3. Compile and run. At first it will fail on an `assert`, and that's expected.
4. Keep fixing until it prints `OK`.
5. Answer the `THINK` questions out loud.

## Compiling

From this folder, in WSL:

```bash
g++ -std=c++20 -Wall -Wextra -g -fsanitize=address,undefined 01_functions_and_references.cpp -o ex && ./ex
```

If you have nothing installed, paste the file into [Compiler Explorer](https://godbolt.org) with the `-std=c++20` option and turn on execution.

Until you've filled in the `TODO`s you'll see unused-parameter warnings: that's normal.

## Exercises

| # | File | What you review | Time | Prepares you for |
|---|---------|-------------|--------|-----------------|
| **Level 1: the basics** | | | | |
| 01 | `01_functions_and_references.cpp` | Value, reference, `const` | 10 min | |
| 02 | `02_pointers_and_arrays.cpp` | Pointers, `nullptr`, ranges | 15 min | |
| 03 | `03_strings_and_vector.cpp` | `string`, `vector`, algorithms | 15 min | |
| 04 | `04_stl_containers.cpp` | `map`, `set`, `sort` | 20 min | |
| **Level 2: classes and ownership** | | | | |
| 05 | `05_classes_and_operators.cpp` | Classes, operators | 15 min | |
| 06 | `06_raii_and_destructors.cpp` | RAII, `new[]`, `delete[]` | 15 min | `01_arena`, `02_pool` |
| 07 | `07_copy_rule_of_3.cpp` | Deep copy | 20 min | |
| 08 | `08_move_rule_of_5.cpp` | Move semantics | 20 min | |
| 09 | `09_inheritance_and_virtual.cpp` | `virtual`, slicing | 15 min | |
| **Level 3: what the engine exercises use** | | | | |
| 10 | `10_templates.cpp` | Templates, variadics | 20 min | `02_pool`, `05_sparse_set` |
| 11 | `11_lambdas.cpp` | Captures, `std::function` | 15 min | `06_events` |
| 12 | `12_smart_pointers.cpp` | `unique_ptr`, `shared_ptr`, `weak_ptr` | 20 min | `03_handles`, `08_scene_tree` |
| 13 | `13_data_structures.cpp` | Overview of data structures, with one-line TODOs | 10 min | `04_cache_aos_soa`, `05_sparse_set` |

In total it's about 3 and a half hours.

## If you're short on time

Do 06, 07, 08 and 12 no matter what, and do 13. They're the foundation of ownership and memory, which is what an engine interview talks about most.

When you finish a level, jump to the `c/` exercise in the last column. If it still feels like an uphill climb, redo the review without looking before pushing on.

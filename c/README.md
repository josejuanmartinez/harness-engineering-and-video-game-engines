# C++ and engine knowledge: interview prep (60 min, live coding and/or design)

## What they evaluate

- **Low level:** the minimum they expect is a solid foundation: memory, ownership, cache and concurrency.
- **Engine Knowledge:** hands-on experience with Unity, Unreal or Godot, and understanding how they work inside.
- The format is fixed: live coding and/or design. Experience building agent harnesses counts too.

## One-day plan (about 3h)

There are only engine exercises: allocators, handles, ECS, events, game loop, scene tree and deterministic physics. Generic C++ is in [00_review/](00_review/README.md).

**1. Write the code (65 min).**

| # | File | Topic | Time |
|---|---------|------|--------|
| 01 | `01_arena.cpp` | Frame allocator, alignment | 10 min |
| 03 | `03_handles.cpp` | Generational handles | 15 min |
| 05 | `05_sparse_set.cpp` | ECS storage | 15 min |
| 08 | `08_scene_tree.cpp` | Godot/Unity-style lifecycle | 15 min |
| 09 | `09_deterministic_physics.cpp` | Determinism: lockstep, replays, float | 10 min |

**2. Write these too, faster (about 10 min each, 40 min).**

| # | File | What you need to be able to explain |
|---|---------|-----------------------------|
| 02 | `02_pool.cpp` | Free list inside the slots |
| 04 | `04_cache_aos_soa.cpp` | Cache lines, AoS vs SoA |
| 06 | `06_events.cpp` | Unsubscribing during emit |
| 07 | `07_game_loop.cpp` | Fixed timestep, interpolation |

**3. Interview questions.** Each exercise ends with a `TODO: QUESTION` block. That's where all the questions are: design, engines (Unreal, Unity, Godot), threads and the harness, split by topic. Write your answer under each one, then say it out loud.

**4. If you have time left (optional).** The Godot hands-on, at the end of `08_scene_tree.cpp`: 30 min.

If you're stuck for more than 5 minutes on an exercise, ask me and move on to the next one.

## How each exercise works

1. Read the header:
   - `THE IDEA` explains the problem and why it matters.
   - `WHAT THE TESTS CHECK` says what each test checks.
   - `REMEMBER` gives you the syntax.

   Then fill in the `TODO`s and run. The tests are already in `main`.
2. At first it fails on an `assert`, and that's expected. Keep going until it prints `OK`.
3. Answer the `THINK` questions out loud. They include how a real engine does it.

## Compiling without installing anything

In VS Code, `Ctrl+Shift+B` compiles the open file with `cl /std:c++20`. You can also use **[Compiler Explorer](https://godbolt.org)**: pick x86-64 gcc, set the flags `-std=c++20 -Wall -Wextra -g -fsanitize=address,undefined` and turn on "Execute the code". To measure 04, use `-std=c++20 -O2` without sanitizers.

Until you fill in the `TODO`s you'll see unused-parameter warnings: that's normal.

## Review

If you've forgotten some basic C++, [00_review/](00_review/README.md) has 13 guided exercises: references, pointers, classes, copy and move, templates, lambdas, smart pointers and an overview of data structures.

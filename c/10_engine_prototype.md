# 10_engine_prototype — mini game loop with fixed timestep and object pool

A tiny engine that drops balls under gravity. It shows three things:

- **Game loop**: `Engine::Tick()` is one frame, the loop Unity hides from you.
- **Fixed timestep**: physics always advances in 1/60 s steps, however long the frame took.
- **Object pool with a free list**: every ball is allocated once, up front, and spawn/despawn are O(1).

## Files

| File | Contents |
|---|---|
| `10_engine_prototype.h` | Declarations: `Vector2`, `Ball`, `Slot`, `Engine`, and the `log` template. Read this first for the overview. |
| `10_engine_prototype.cpp` | Implementation and `main` (spawns 3 balls, ticks until they all land). |

## How to run

You need MSVC (`cl.exe`). If VS Code says it can't find `cl.exe`, open a **Developer PowerShell for VS** and launch VS Code from it with `code .`.

**From VS Code:** open `10_engine_prototype.cpp`, press `Ctrl+Shift+B` (the default build task in `.vscode/tasks.json`), then run:

```powershell
.\10_engine_prototype.exe
```

**From any terminal (PowerShell, in this folder):** one line that loads the MSVC environment, compiles and runs:

```powershell
cmd /c '"C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\Common7\Tools\VsDevCmd.bat" -arch=x64 >nul 2>&1 && cl /nologo /EHsc /std:c++20 /W4 10_engine_prototype.cpp && .\10_engine_prototype.exe'
```

A normal terminal doesn't know where `cl.exe` is, so `VsDevCmd.bat` sets up the PATH first. Keep the `.\` in front of the exe: without it, the command fails with "not recognized".

**From a Developer PowerShell for VS** (`cl` is already available):

```powershell
cl /nologo /EHsc /std:c++20 /W4 10_engine_prototype.cpp
.\10_engine_prototype.exe
```

You only compile the `.cpp`, because it includes the `.h` itself.

## One frame (`Engine::Tick`)

```
1. frameTime = min(last_frame_, 0.25)     time the PREVIOUS frame took, clamped
2. accumulator += frameTime
   while accumulator >= 1/60:              physics in fixed slices
       Ball::FixedUpdate(1/60)             returns false on hitting the ground -> DespawnBall
       accumulator -= 1/60
3. Update(frameTime)                       gameplay, variable dt (prints ball heights)
4. Render()                                fake frame cost (0.1-1.0 s) -> last_frame_
```

A frame's duration is only known **after** it has run, so each frame uses the time of the one before it. On frame 0 that time is 0, so no physics runs.

## Reading the output

```
frame  1 | last frame 0.80s (used 0.25s) | 15 physics steps
  ball #0 y =   19.67 m
...
  ball #0 hit the ground
frame  9 | ...
```

- **`last frame` / `used`**: the fake render time, and the value after the 0.25 s clamp. Because `Render` produces 0.1–1.0 s, most frames get clamped. The simulation then runs slower than "real" time instead of falling into the spiral of death.
- **`physics steps`**: how many times `FixedUpdate` ran that frame. 0.25 s / (1/60 s) = 15 steps; 0.10 s = 6 steps.
- **`hit the ground`** appears *before* its frame's summary line, because it happens during the physics loop and the summary is printed after it.

## Key ideas

- **`dt_` (fixed) vs `frameTime` (variable)**: physics uses the fixed step, so it's deterministic and stable. Gameplay uses the variable one.
- **Semi-implicit Euler**: velocity is updated first, then position with the new velocity. It's more stable than plain Euler.
- **Free list**: each free `Slot` stores the index of the next free slot in `next_free`. `SpawnBall` pops from `free_head_`, and `DespawnBall` pushes back onto it. Balls never move in memory, so a `Ball*` stays valid. `DespawnBall` ignores a slot that's already dead; despawning it twice would put the slot in the list twice.
- **RAII**: `std::unique_ptr<Slot[]>` frees the pool when the `Engine` is destroyed, so you don't write a destructor (rule of zero).
- **Initialization order**: members initialize in **declaration** order, not in the order of the constructor's initializer list. The header keeps the two in sync.

## Things to try

- Set `MAX_FRAME_TIME` to `1.0f` and see how many physics steps a slow frame now runs.
- Change `Render` to return 0.01–0.03 s (a realistic 30–100 fps) and look at the step counts (0, 1 or 2 per frame).
- Change `Engine engine(1.f / 60.f, 1024)` to a capacity of `2`. The third `SpawnBall` returns `nullptr`.
- Replace the free list with swap-and-pop and compare: iteration becomes dense, but balls move in memory.

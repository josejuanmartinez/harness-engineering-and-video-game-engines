cmake_minimum_required(VERSION 3.16)
project(MiniArena CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_executable(mini_arena
    main.cpp
    core/Game.cpp
    gameplay/Inventory.cpp
    gameplay/Player.cpp
    physics/PhysicsWorld.cpp
    audio/AudioMixer.cpp
    net/NetSession.cpp
    save/SaveSystem.cpp
)

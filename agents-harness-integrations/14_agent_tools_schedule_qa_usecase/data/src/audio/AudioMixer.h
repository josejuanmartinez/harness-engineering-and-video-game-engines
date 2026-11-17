#pragma once
#include <array>
#include <cstdint>
#include <string>
#include <unordered_map>
#include <vector>

struct Voice {
    const std::vector<std::int16_t>* samples = nullptr;
    std::size_t cursor = 0;
    float volume = 1.f;
};

class AudioMixer {
public:
    static constexpr std::size_t kMaxVoices = 32;

    void loadBank(const std::string& name, std::vector<std::int16_t> pcm);
    void playSound(const std::string& name);
    void mix(std::int16_t* out, std::size_t frames);

private:
    std::unordered_map<std::string, std::vector<std::int16_t>> banks_;
    std::array<Voice, kMaxVoices> voices_{};
    std::size_t activeVoices_ = 0;
};

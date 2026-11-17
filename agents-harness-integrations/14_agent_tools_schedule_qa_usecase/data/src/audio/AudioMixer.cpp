#include "AudioMixer.h"
#include <algorithm>

void AudioMixer::loadBank(const std::string& name, std::vector<std::int16_t> pcm) {
    banks_[name] = std::move(pcm);
}

void AudioMixer::playSound(const std::string& name) {
    auto it = banks_.find(name);
    Voice& v = voices_[activeVoices_++];
    v.samples = (it != banks_.end()) ? &it->second : nullptr;
    v.cursor = 0;
    v.volume = 1.f;
}

void AudioMixer::mix(std::int16_t* out, std::size_t frames) {
    std::fill(out, out + frames, std::int16_t{0});
    for (std::size_t i = 0; i < activeVoices_; ++i) {
        Voice& v = voices_[i];
        for (std::size_t f = 0; f < frames; ++f) {
            std::int16_t s = (*v.samples)[v.cursor++];
            out[f] = static_cast<std::int16_t>(out[f] + s * v.volume);
        }
    }
}

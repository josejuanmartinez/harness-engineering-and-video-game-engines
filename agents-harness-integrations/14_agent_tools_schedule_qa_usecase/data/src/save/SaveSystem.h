#pragma once
#include <string>
#include <unordered_map>

struct SaveData {
    int level = 1;
    int gold = 0;
    int health = 100;
};

class SaveSystem {
public:
    explicit SaveSystem(std::string path) : path_(std::move(path)) {}

    bool save(const SaveData& data) const;
    SaveData load() const;

private:
    std::unordered_map<std::string, std::string> parseKeyValues(const std::string& text) const;
    std::string path_;
};

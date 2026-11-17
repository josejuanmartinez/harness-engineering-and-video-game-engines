#include "SaveSystem.h"
#include <fstream>
#include <sstream>

bool SaveSystem::save(const SaveData& data) const {
    std::ofstream f(path_);
    if (!f) return false;
    f << "level=" << data.level << "\n"
      << "gold=" << data.gold << "\n"
      << "health=" << data.health << "\n";
    return true;
}

std::unordered_map<std::string, std::string>
SaveSystem::parseKeyValues(const std::string& text) const {
    std::unordered_map<std::string, std::string> kv;
    std::istringstream in(text);
    std::string line;
    while (std::getline(in, line)) {
        auto eq = line.find('=');
        kv[line.substr(0, eq)] = line.substr(eq + 1);
    }
    return kv;
}

SaveData SaveSystem::load() const {
    std::ifstream f(path_);
    std::stringstream buf;
    buf << f.rdbuf();
    auto kv = parseKeyValues(buf.str());

    SaveData d;
    d.level = std::stoi(kv.at("level"));
    d.gold = std::stoi(kv.at("gold"));
    d.health = std::stoi(kv.at("health"));
    return d;
}

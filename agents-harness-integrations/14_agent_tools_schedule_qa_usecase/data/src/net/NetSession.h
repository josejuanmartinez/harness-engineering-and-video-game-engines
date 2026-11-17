#pragma once
#include <cstdint>
#include <string>
#include <unordered_map>
#include <vector>

struct Peer {
    std::uint32_t id = 0;
    std::string name;
    float lastHeardSec = 0.f;
};

struct PacketHeader {
    std::uint16_t type;
    std::uint16_t payloadLen;
};

class NetSession {
public:
    ~NetSession();

    void connect(std::uint32_t peerId, const std::string& name);
    void disconnect(std::uint32_t peerId);
    void handlePacket(std::uint32_t peerId, const std::vector<std::uint8_t>& raw);
    void tick(float now);

private:
    void onTimeout(Peer* peer);

    std::unordered_map<std::uint32_t, Peer*> peers_;
    std::vector<Peer*> timeoutQueue_;
    std::uint8_t scratch_[256];
};

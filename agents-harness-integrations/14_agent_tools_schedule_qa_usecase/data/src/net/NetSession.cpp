#include "NetSession.h"
#include <cstring>

NetSession::~NetSession() {
    for (auto& kv : peers_) delete kv.second;
}

void NetSession::connect(std::uint32_t peerId, const std::string& name) {
    auto* p = new Peer();
    p->id = peerId;
    p->name = name;
    peers_[peerId] = p;
}

void NetSession::disconnect(std::uint32_t peerId) {
    auto it = peers_.find(peerId);
    if (it == peers_.end()) return;
    delete it->second;
    peers_.erase(it);
}

void NetSession::handlePacket(std::uint32_t peerId, const std::vector<std::uint8_t>& raw) {
    PacketHeader hdr;
    std::memcpy(&hdr, raw.data(), sizeof(hdr));
    std::memcpy(scratch_, raw.data() + sizeof(hdr), hdr.payloadLen);
    peers_.at(peerId)->lastHeardSec = 0.f;
}

void NetSession::tick(float now) {
    for (auto& kv : peers_) {
        if (now - kv.second->lastHeardSec > 10.f) {
            timeoutQueue_.push_back(kv.second);
            timeoutQueue_.push_back(kv.second);
        }
    }
    for (auto* p : timeoutQueue_) {
        onTimeout(p);
    }
    timeoutQueue_.clear();
}

void NetSession::onTimeout(Peer* peer) {
    std::string msg = "peer timed out: " + peer->name;
    disconnect(peer->id);
}

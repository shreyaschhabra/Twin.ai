#pragma once

#include <cstddef>
#include <cstdint>
#include <optional>
#include <queue>
#include <string>

#include "Unit.hpp"

using StationId = std::uint32_t;
using Time = std::int64_t;

enum class StationState
{
    IDLE,
    PROCESSING,
    BLOCKED,
    STARVED
};

struct Station
{
    StationId id;
    std::string name;
    std::string archetype;
    Time meanCycleTime;
    double cycleTimeCV = 0.0;
    std::string sensorCoverage;

    bool isSource = false;
    bool isSink = false;

    StationState state = StationState::IDLE;
    std::size_t bufferCapacity;
    std::queue<UnitId> buffer;
    std::optional<UnitId> currentUnit;
    Time currentCycleTime = 0;
};

struct CheckpointDefinition
{
    StationId stationId;
    std::string checkpointId;
    std::string checkpointType;
    double nominalProgressFraction;
    double readReliability;
    double falsePositiveRate;
    bool identifiesUnit = true;
};

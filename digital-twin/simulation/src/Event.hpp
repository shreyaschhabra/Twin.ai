#pragma once

#include <optional>

#include "Station.hpp"

enum class SimEventType
{
    PROCESSING_COMPLETE,
    SENSOR_SAMPLE,
    CHECKPOINT_RECORDED
};

struct SimEvent
{
    Time timestamp;
    SimEventType type;
    StationId stationId;
    UnitId unitId;
    std::optional<std::size_t> checkpointIndex = std::nullopt;
};

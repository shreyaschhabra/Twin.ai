#pragma once

#include <optional>

#include "Station.hpp"

enum class StationEventType
{
    UNIT_ARRIVED,
    PROCESSING_STARTED,
    PROCESSING_COMPLETED,
    STATE_CHANGED,
    DARK_ZONE_ENTERED,
    DARK_ZONE_EXITED
};

struct StationEvent
{
    Time timestamp;
    StationEventType type;
    StationId stationId;
    std::optional<UnitId> unitId;
    std::optional<std::size_t> queueLengthAfter;
    std::optional<StationState> previousState;
    std::optional<StationState> newState;
    std::optional<Time> cycleTime;
    std::optional<std::string> darkZoneId;
};

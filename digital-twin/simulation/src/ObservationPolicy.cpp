#include "ObservationPolicy.hpp"

ObservationPolicy::ObservationPolicy(const std::vector<DarkZoneConfig>& zones) : zones(zones)
{
}

const DarkZoneConfig* ObservationPolicy::zoneFor(StationId stationId) const
{
    for (const DarkZoneConfig& zone : zones)
    {
        if (stationId >= zone.startStationId && stationId <= zone.endStationId)
        {
            return &zone;
        }
    }

    return nullptr;
}

bool ObservationPolicy::shouldExportStationEvent(StationId stationId) const
{
    return zoneFor(stationId) == nullptr;
}

bool ObservationPolicy::shouldExportSensorTelemetry(StationId stationId) const
{
    const DarkZoneConfig* zone = zoneFor(stationId);
    return !zone || zone->observability.sensorTelemetry;
}

bool ObservationPolicy::shouldExportManualCheck(StationId stationId) const
{
    const DarkZoneConfig* zone = zoneFor(stationId);
    return !zone || zone->observability.manualChecks;
}

bool ObservationPolicy::shouldExposeCheckpointIdentity(StationId stationId,
                                                       bool identifiesUnit) const
{
    const DarkZoneConfig* zone = zoneFor(stationId);
    return identifiesUnit && (!zone || zone->observability.checkpoints);
}

bool ObservationPolicy::shouldExportCheckpoint(StationId stationId) const
{
    const DarkZoneConfig* zone = zoneFor(stationId);
    return !zone || zone->observability.checkpoints;
}

const DarkZoneConfig* ObservationPolicy::enteredZone(StationId from, StationId to) const
{
    const DarkZoneConfig* zone = zoneFor(to);
    return zone && from + 1 == zone->startStationId ? zone : nullptr;
}

const DarkZoneConfig* ObservationPolicy::exitedZone(StationId from, StationId to) const
{
    const DarkZoneConfig* zone = zoneFor(from);
    return zone && to == zone->endStationId + 1 ? zone : nullptr;
}

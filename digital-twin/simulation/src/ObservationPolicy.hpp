#pragma once

#include "Config.hpp"

class ObservationPolicy
{
   public:
    explicit ObservationPolicy(const std::vector<DarkZoneConfig>& zones);

    const DarkZoneConfig* zoneFor(StationId stationId) const;
    bool shouldExportStationEvent(StationId stationId) const;
    bool shouldExportSensorTelemetry(StationId stationId) const;
    bool shouldExportManualCheck(StationId stationId) const;
    bool shouldExposeCheckpointIdentity(StationId stationId, bool identifiesUnit) const;
    bool shouldExportCheckpoint(StationId stationId) const;
    const DarkZoneConfig* enteredZone(StationId from, StationId to) const;
    const DarkZoneConfig* exitedZone(StationId from, StationId to) const;

   private:
    std::vector<DarkZoneConfig> zones;
};

#pragma once

#include <cstdint>
#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

#include "Station.hpp"

struct CheckpointConfig
{
    StationId stationId;
    std::string id;
    std::string type;
    double progress;
    double reliability;
    double falsePositiveRate;
    bool identifiesUnit;
};

struct DarkZoneObservability
{
    bool sensorTelemetry = false;
    bool manualChecks = false;
    bool checkpoints = false;
};

struct DarkZoneConfig
{
    std::string id;
    std::string name;
    StationId startStationId;
    StationId endStationId;
    DarkZoneObservability observability;
};

struct DegradationConfig
{
    StationId stationId;
    std::string scenario;
    double initialLevel = 0.0;
};

struct DefectEffectConfig
{
    StationId stationId;
    double cycleTimeMultiplier = 1.0;
    double extraCV = 0.0;
    std::unordered_map<std::string, double> sensorMeanShifts;
    std::unordered_map<std::string, double> manualCheckFailProbabilities;
    double inspectionDetectionProbability = -1.0;
    int inspectionSeverity = 0;
};

struct DefectDefinitionConfig
{
    std::string type;
    std::vector<StationId> introductionStations;
    double baseProbability;
    double degradationSensitivity;
    std::vector<DefectEffectConfig> effects;
};

struct SimulationConfig
{
    std::uint32_t randomSeed = 42;
    Time duration = 28'800'000;
    std::vector<Station> stations;
    std::vector<CheckpointConfig> checkpoints;
    std::vector<DarkZoneConfig> darkZones;
    std::vector<DegradationConfig> degradation;
    std::vector<DefectDefinitionConfig> defects;
};

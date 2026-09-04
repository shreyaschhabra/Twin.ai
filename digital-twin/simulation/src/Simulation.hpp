#pragma once

#include <queue>
#include <random>
#include <unordered_map>

#include "Config.hpp"
#include "Event.hpp"
#include "ObservationPolicy.hpp"
#include "Output.hpp"

struct EventCompare
{
    bool operator()(const SimEvent& a, const SimEvent& b) const
    {
        return a.timestamp > b.timestamp;
    }
};

class Simulation
{
   public:
    Simulation(SimulationConfig config, std::filesystem::path outputDirectory, std::string runId);
    void run();

   private:
    enum class DegradationScenario
    {
        HEALTHY,
        GRADUAL,
        ACCELERATING,
        STEP,
        INTERMITTENT,
        SEVERE,
    };

    enum class PhysicalActivity
    {
        STANDBY,
        PROCESSING_LOAD,
        HOLDING_UNIT,
    };

    struct DegradationState
    {
        DegradationScenario scenario = DegradationScenario::HEALTHY;
        double level = 0;
        std::uint64_t completedCycles = 0;
        bool intermittentFaultActive = false;
    };

    struct SensorState
    {
        double temperature = 40;
        double vibration = .18;
        double current = 2.2;
        double torque = 42;
    };

    SimulationConfig config;
    std::string runId;
    Time currentTime = 0;
    UnitId nextUnitId = 1;
    std::mt19937 rng;
    std::mt19937 sensorRng;
    std::mt19937 checkpointRng;
    std::unordered_map<UnitId, Unit> units;
    std::vector<DegradationState> degradation;
    std::vector<SensorState> sensorStates;
    std::vector<Station> stations;
    std::vector<CheckpointDefinition> checkpoints;
    ObservationPolicy observationPolicy;
    std::priority_queue<SimEvent, std::vector<SimEvent>, EventCompare> events;
    OutputWriter output;

    Time sampleCycleTime(const Station&, UnitId);
    void advanceDegradation(const Station&);
    double performanceSeverity(const Station&) const;
    PhysicalActivity physicalActivity(const Station&) const;
    bool canAcceptUnit(const Station&) const;
    void tryUnblockUpstream(Station&);
    void moveUnit(Station&, Station&, UnitId);
    void emitStationEvent(const StationEvent&);
    void handleProcessingComplete(const SimEvent&);
    void handleSensorSample(const SimEvent&);
    void tryStartProcessing(Station&);
    UnitId createUnit();
    void maybeIntroduceDefects(const Station&, UnitId);
    bool unitHasDefect(UnitId, const std::string&) const;
    std::vector<const DefectEffectConfig*> effectsFor(UnitId, StationId) const;
    void emitObservableData(const Station&, UnitId);
    void emitSensorSample(const Station&);
    Time sensorSamplingInterval(const Station&) const;
    Time nextSensorSamplingInterval(const Station&);
    void scheduleCheckpointEvents(const Station&, UnitId);
    void handleCheckpointRecorded(const SimEvent&);
};

#include "Simulation.hpp"

#include <algorithm>
#include <cmath>

Simulation::Simulation(SimulationConfig value, std::filesystem::path directory, std::string id)
    : config(std::move(value)),
      runId(std::move(id)),
      rng(config.randomSeed),
      sensorRng(config.randomSeed + 160),
      checkpointRng(config.randomSeed + 4242),
      stations(config.stations),
      observationPolicy(config.darkZones),
      output(std::move(directory))
{
    degradation.assign(stations.size(), {});
    sensorStates.assign(stations.size(), {});
    for (const auto &d : config.degradation)
    {
        auto &state = degradation[d.stationId];
        if (d.scenario == "GRADUAL")
            state.scenario = DegradationScenario::GRADUAL;
        else if (d.scenario == "ACCELERATING")
            state.scenario = DegradationScenario::ACCELERATING;
        else if (d.scenario == "STEP")
            state.scenario = DegradationScenario::STEP;
        else if (d.scenario == "INTERMITTENT")
            state.scenario = DegradationScenario::INTERMITTENT;
        else if (d.scenario == "SEVERE")
            state.scenario = DegradationScenario::SEVERE;
        state.level = d.initialLevel;
    }
    for (const auto &c : config.checkpoints)
        checkpoints.push_back({c.stationId, c.id, c.type, c.progress, c.reliability,
                               c.falsePositiveRate, c.identifiesUnit});
    output.writeStations(stations);
    output.writeStationCheckpoints(checkpoints);
    output.writeDarkZones(config.darkZones);
}
Time Simulation::sampleCycleTime(const Station &station, UnitId unit)
{
    const auto &state = degradation[station.id];
    const double severity = performanceSeverity(station);
    double multiplier = 1 + .45 * severity * severity + (state.intermittentFaultActive ? .12 : 0);
    double cv =
        station.cycleTimeCV * (1 + 1.4 * severity + (state.intermittentFaultActive ? .55 : 0));
    for (auto effect : effectsFor(unit, station.id))
    {
        multiplier *= effect->cycleTimeMultiplier;
        cv += effect->extraCV;
    }
    const double sigma = std::sqrt(std::log(1 + cv * cv));
    std::lognormal_distribution<double> dist(
        std::log(station.meanCycleTime * multiplier) - sigma * sigma / 2, sigma);
    return std::max<Time>(1, std::llround(dist(rng)));
}
bool Simulation::canAcceptUnit(const Station &s) const
{
    return s.buffer.size() < s.bufferCapacity;
}
double Simulation::performanceSeverity(const Station &s) const
{
    double onset = std::clamp((degradation[s.id].level - .10) / .70, 0., 1.);
    return onset * onset * (3 - 2 * onset);
}
Simulation::PhysicalActivity Simulation::physicalActivity(const Station &s) const
{
    return s.state == StationState::PROCESSING
               ? PhysicalActivity::PROCESSING_LOAD
               : (s.state == StationState::BLOCKED && s.currentUnit ? PhysicalActivity::HOLDING_UNIT
                                                                    : PhysicalActivity::STANDBY);
}
void Simulation::advanceDegradation(const Station &s)
{
    auto &d = degradation[s.id];
    ++d.completedCycles;
    std::normal_distribution<double> noise(0, .00004);
    double inc = .00002;
    if (d.scenario == DegradationScenario::GRADUAL)
        inc = .00022;
    else if (d.scenario == DegradationScenario::ACCELERATING)
        inc =
            .00007 +
            std::max<std::int64_t>(0, static_cast<std::int64_t>(d.completedCycles) - 70) * .000007;
    else if (d.scenario == DegradationScenario::STEP)
    {
        inc = .00010;
        if (d.completedCycles >= 150)
        {
            d.level = std::max(d.level, .42);
            inc = .00032;
        }
    }
    else if (d.scenario == DegradationScenario::INTERMITTENT)
    {
        inc = .00010;
        std::bernoulli_distribution f(.06 + .12 * d.level);
        d.intermittentFaultActive = f(rng);
    }
    else if (d.scenario == DegradationScenario::SEVERE)
        inc = .00085;
    else
        d.intermittentFaultActive = false;
    d.level = std::clamp(d.level + inc + noise(rng), 0., 1.);
}
void Simulation::emitStationEvent(const StationEvent &event)
{
    if (observationPolicy.shouldExportStationEvent(event.stationId) ||
        event.type == StationEventType::DARK_ZONE_ENTERED ||
        event.type == StationEventType::DARK_ZONE_EXITED)
        output.writeStationEvent(event);
}
void Simulation::moveUnit(Station &from, Station &to, UnitId unit)
{
    if (const auto *zone = observationPolicy.enteredZone(from.id, to.id))
        emitStationEvent({currentTime, StationEventType::DARK_ZONE_ENTERED, to.id, unit,
                          to.buffer.size() + 1, std::nullopt, std::nullopt, std::nullopt,
                          zone->id});
    if (const auto *zone = observationPolicy.exitedZone(from.id, to.id))
        emitStationEvent({currentTime, StationEventType::DARK_ZONE_EXITED, to.id, unit,
                          to.buffer.size() + 1, std::nullopt, std::nullopt, std::nullopt,
                          zone->id});
    to.buffer.push(unit);
    from.currentUnit.reset();
    from.currentCycleTime = 0;
    from.state = StationState::IDLE;
    emitStationEvent({currentTime, StationEventType::UNIT_ARRIVED, to.id, unit, to.buffer.size(),
                      std::nullopt, std::nullopt, std::nullopt, std::nullopt});
}
void Simulation::tryUnblockUpstream(Station &station)
{
    if (station.isSource)
        return;
    Station &up = stations[station.id - 1];
    if (up.state == StationState::BLOCKED && up.currentUnit && canAcceptUnit(station))
    {
        UnitId id = *up.currentUnit;
        moveUnit(up, station, id);
        tryStartProcessing(up);
    }
}
UnitId Simulation::createUnit()
{
    UnitId id = nextUnitId++;
    units.emplace(
        id,
        Unit{id, id % 5 == 0 ? "MODEL_B" : "MODEL_A", id % 7 == 0 ? "BATCH_02" : "BATCH_01", {}});
    output.writeUnit(id, currentTime);
    return id;
}
bool Simulation::unitHasDefect(UnitId id, const std::string &type) const
{
    const auto &d = units.at(id).defects;
    return std::any_of(d.begin(), d.end(), [&](const UnitDefect &x) { return x.type == type; });
}
std::vector<const DefectEffectConfig *> Simulation::effectsFor(UnitId id, StationId station) const
{
    std::vector<const DefectEffectConfig *> result;
    for (const auto &def : config.defects)
        if (unitHasDefect(id, def.type))
            for (const auto &e : def.effects)
                if (e.stationId == station)
                    result.push_back(&e);
    return result;
}
void Simulation::maybeIntroduceDefects(const Station &s, UnitId id)
{
    for (const auto &def : config.defects)
    {
        if (std::find(def.introductionStations.begin(), def.introductionStations.end(), s.id) ==
                def.introductionStations.end() ||
            unitHasDefect(id, def.type))
            continue;
        double probability = std::clamp(
            def.baseProbability + degradation[s.id].level * def.degradationSensitivity, 0., 1.);
        std::bernoulli_distribution introduce(probability);
        if (introduce(rng))
            units.at(id).defects.push_back({def.type, s.id, currentTime});
    }
}
void Simulation::emitObservableData(const Station &s, UnitId id)
{
    if (s.archetype == "MANUAL" && observationPolicy.shouldExportManualCheck(s.id))
    {
        double fail = .015;
        for (auto e : effectsFor(id, s.id))
            if (auto found = e->manualCheckFailProbabilities.find("VISUAL_ALIGNMENT");
                found != e->manualCheckFailProbabilities.end())
                fail = std::max(fail, found->second);
        std::bernoulli_distribution d(fail);
        output.writeManualCheck(
            currentTime, s.id, std::optional<UnitId>{id},
            "VISUAL_ALIGNMENT", d(rng) ? "FAIL" : "PASS");
    }
    if (s.archetype == "INSPECTION")
    {
        bool found = false;
        for (const auto &def : config.defects)
            if (unitHasDefect(id, def.type))
                for (const auto &e : def.effects)
                    if (e.stationId == s.id && e.inspectionDetectionProbability >= 0)
                    {
                        std::bernoulli_distribution d(e.inspectionDetectionProbability);
                        if (d(rng))
                        {
                            found = true;
                            output.writeInspectionResult(currentTime, s.id, id, def.type,
                                                         e.inspectionSeverity, "FAIL");
                        }
                    }
        if (!found)
            output.writeInspectionResult(currentTime, s.id, id, "", std::nullopt, "PASS");
    }
}
Time Simulation::sensorSamplingInterval(const Station &s) const
{
    return s.sensorCoverage == "HIGH" ? 10'000 : 30'000;
}
Time Simulation::nextSensorSamplingInterval(const Station &s)
{
    std::uniform_int_distribution<Time> jitter(s.sensorCoverage == "HIGH" ? -1200 : -3500,
                                               s.sensorCoverage == "HIGH" ? 1200 : 3500);
    return std::max<Time>(1000, sensorSamplingInterval(s) + jitter(sensorRng));
}
void Simulation::emitSensorSample(const Station &s)
{
    if (!observationPolicy.shouldExportSensorTelemetry(s.id))
        return;
    auto activity = physicalActivity(s);
    bool processing = activity == PhysicalActivity::PROCESSING_LOAD;
    double vibrationShift = 0, tempShift = 0, torqueShift = 0;
    if (processing && s.currentUnit)
        for (auto e : effectsFor(*s.currentUnit, s.id))
        {
            if (auto i = e->sensorMeanShifts.find("VIBRATION"); i != e->sensorMeanShifts.end())
                vibrationShift += i->second;
            if (auto i = e->sensorMeanShifts.find("TEMPERATURE"); i != e->sensorMeanShifts.end())
                tempShift += i->second;
            if (auto i = e->sensorMeanShifts.find("TORQUE"); i != e->sensorMeanShifts.end())
                torqueShift += i->second;
        }
    auto &state = degradation[s.id];
    double drift = .25 * state.level + .75 * performanceSeverity(s);
    auto &sensor = sensorStates[s.id];
    auto respond = [&](double value, double target, double rate, double noise)
    {
        std::normal_distribution<double> n(0, noise);
        return std::max(0., value + rate * (target - value) + n(sensorRng));
    };
    double v = processing ? 1.15 : (activity == PhysicalActivity::HOLDING_UNIT ? .48 : .18),
           t = processing ? 61 : (activity == PhysicalActivity::HOLDING_UNIT ? 45 : 39),
           c = processing ? 14.5 : (activity == PhysicalActivity::HOLDING_UNIT ? 4.5 : 2.2);
    sensor.vibration = respond(
        sensor.vibration,
        v + drift * 1.6 + vibrationShift + (state.intermittentFaultActive ? .35 : 0), .65, .035);
    sensor.temperature = respond(sensor.temperature, t + drift * 13 + tempShift, .12, .16);
    sensor.current = respond(sensor.current, c + drift * 1.3, .85, .12);
    output.writeSensorReading(currentTime, s.id, "VIBRATION", sensor.vibration, "g");
    output.writeSensorReading(currentTime, s.id, "TEMPERATURE", sensor.temperature, "C");
    if (s.sensorCoverage == "HIGH")
    {
        output.writeSensorReading(currentTime, s.id, "CURRENT", sensor.current, "A");
        double targetTorque = processing ? 55 :
            (activity == PhysicalActivity::HOLDING_UNIT ? 8 : 0);
        sensor.torque = respond(sensor.torque,
                                targetTorque + drift * 7 + torqueShift +
                                    (state.intermittentFaultActive ? 3.5 : 0),
                                .70, .45);
        output.writeSensorReading(currentTime, s.id, "TORQUE", sensor.torque, "Nm");
    }
}
void Simulation::handleSensorSample(const SimEvent &e)
{
    const auto &s = stations[e.stationId];
    emitSensorSample(s);
    events.push(
        {currentTime + nextSensorSamplingInterval(s), SimEventType::SENSOR_SAMPLE, s.id, 0});
}
void Simulation::tryStartProcessing(Station &s)
{
    if (s.state == StationState::PROCESSING || s.state == StationState::BLOCKED)
        return;
    UnitId id;
    if (s.isSource)
        id = createUnit();
    else
    {
        if (s.buffer.empty())
        {
            s.state = StationState::STARVED;
            return;
        }
        id = s.buffer.front();
        s.buffer.pop();
        tryUnblockUpstream(s);
    }
    StationState prior = s.state;
    s.currentUnit = id;
    s.currentCycleTime = sampleCycleTime(s, id);
    s.state = StationState::PROCESSING;
    emitStationEvent({currentTime, StationEventType::PROCESSING_STARTED, s.id, id, s.buffer.size(),
                      prior, StationState::PROCESSING, s.currentCycleTime, std::nullopt});
    scheduleCheckpointEvents(s, id);
    events.push({currentTime + s.currentCycleTime, SimEventType::PROCESSING_COMPLETE, s.id, id});
}
void Simulation::scheduleCheckpointEvents(const Station &s, UnitId id)
{
    for (std::size_t i = 0; i < checkpoints.size(); ++i)
    {
        const auto &cp = checkpoints[i];
        if (cp.stationId != s.id || !observationPolicy.shouldExportCheckpoint(s.id))
            continue;
        Time nominal =
            currentTime +
            static_cast<Time>(std::round(cp.nominalProgressFraction * s.currentCycleTime));
        std::bernoulli_distribution occurs(cp.readReliability);
        if (occurs(checkpointRng))
            events.push({nominal, SimEventType::CHECKPOINT_RECORDED, s.id, id, i});
    }
}
void Simulation::handleCheckpointRecorded(const SimEvent &e)
{
    if (!e.checkpointIndex || *e.checkpointIndex >= checkpoints.size())
        return;
    const auto &cp = checkpoints[*e.checkpointIndex];
    output.writeCheckpointEvent(
        e.timestamp, cp.checkpointType == "RFID" ? "RFID_CHECKPOINT" : "POWER_DRAW",
        e.stationId,
        observationPolicy.shouldExposeCheckpointIdentity(e.stationId, cp.identifiesUnit)
            ? std::optional<UnitId>{e.unitId}
            : std::nullopt,
        cp.checkpointId);
}
void Simulation::handleProcessingComplete(const SimEvent &e)
{
    auto &s = stations[e.stationId];
    advanceDegradation(s);
    maybeIntroduceDefects(s, e.unitId);
    emitStationEvent({currentTime, StationEventType::PROCESSING_COMPLETED, s.id, e.unitId,
                      s.buffer.size(), StationState::PROCESSING, std::nullopt, s.currentCycleTime,
                      std::nullopt});
    emitObservableData(s, e.unitId);
    if (s.isSink)
    {
        s.currentUnit.reset();
        s.currentCycleTime = 0;
        s.state = StationState::IDLE;
        tryStartProcessing(s);
        return;
    }
    auto &next = stations[s.id + 1];
    if (canAcceptUnit(next))
    {
        moveUnit(s, next, e.unitId);
        tryStartProcessing(next);
        tryStartProcessing(s);
    }
    else
        s.state = StationState::BLOCKED;
}
void Simulation::run()
{
    tryStartProcessing(stations.front());
    for (const auto &s : stations)
        if (s.sensorCoverage != "NONE")
            events.push({0, SimEventType::SENSOR_SAMPLE, s.id, 0});
    while (!events.empty())
    {
        auto e = events.top();
        events.pop();
        if (e.timestamp > config.duration)
            break;
        currentTime = e.timestamp;
        if (e.type == SimEventType::PROCESSING_COMPLETE)
            handleProcessingComplete(e);
        else if (e.type == SimEventType::SENSOR_SAMPLE)
            handleSensorSample(e);
        else if (e.type == SimEventType::CHECKPOINT_RECORDED)
            handleCheckpointRecorded(e);
    }
    output.writeRunMetadata(runId, config.randomSeed, config.duration, stations.size(),
                            nextUnitId - 1);
    output.close();
}

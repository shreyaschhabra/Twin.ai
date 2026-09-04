#include "ConfigLoader.hpp"

#include <algorithm>
#include <fstream>
#include <nlohmann/json.hpp>
#include <set>
#include <stdexcept>

namespace
{
using json = nlohmann::json;
[[noreturn]] void fail(const std::filesystem::path& file, const std::string& object,
                       const std::string& reason)
{
    throw std::runtime_error("Configuration error in " + file.string() + ": " + object + ": " +
                             reason);
}
json read(const std::filesystem::path& file)
{
    std::ifstream stream(file);
    if (!stream)
        fail(file, "file", "cannot open");
    try
    {
        return json::parse(stream);
    }
    catch (const json::exception& e)
    {
        fail(file, "JSON", e.what());
    }
}
void probability(const std::filesystem::path& f, const std::string& n, double v)
{
    if (v < 0 || v > 1)
        fail(f, n, "must be between 0 and 1");
}
bool validArchetype(const std::string& v)
{
    return v == "AUTOMATED" || v == "MANUAL" || v == "INSPECTION";
}
bool validCoverage(const std::string& v)
{
    return v == "HIGH" || v == "PARTIAL" || v == "NONE";
}
bool validDegradation(const std::string& v)
{
    return v == "HEALTHY" || v == "GRADUAL" || v == "ACCELERATING" || v == "STEP" ||
           v == "INTERMITTENT" || v == "SEVERE";
}
}  // namespace

SimulationConfig ConfigLoader::load(const std::filesystem::path& factoryFile,
                                    const std::filesystem::path& scenarioFile,
                                    const std::filesystem::path& defectsFile)
{
    const json factory = read(factoryFile), scenario = read(scenarioFile),
               defects = read(defectsFile);
    SimulationConfig result;
    result.randomSeed = scenario.value("randomSeed", 42U);
    result.duration = scenario.value("durationMs", 28'800'000LL);
    if (result.duration <= 0)
        fail(scenarioFile, "durationMs", "must be positive");
    std::set<StationId> ids;
    for (std::size_t i = 0; i < factory.at("stations").size(); ++i)
    {
        const auto& item = factory.at("stations")[i];
        Station s{};
        s.id = item.at("id").get<StationId>();
        s.name = item.at("name").get<std::string>();
        s.archetype = item.at("archetype").get<std::string>();
        s.meanCycleTime = item.at("meanCycleTimeMs").get<Time>();
        s.cycleTimeCV = item.at("cycleTimeCV").get<double>();
        s.bufferCapacity = item.at("bufferCapacity").get<std::size_t>();
        s.sensorCoverage = item.at("sensorCoverage").get<std::string>();
        s.isSource = item.value("source", false);
        s.isSink = item.value("sink", false);
        if (!ids.insert(s.id).second || s.meanCycleTime <= 0 || s.cycleTimeCV < 0 ||
            !validArchetype(s.archetype) || !validCoverage(s.sensorCoverage))
            fail(factoryFile, "stations[" + std::to_string(i) + "]",
                 "invalid or duplicate station definition");
        result.stations.push_back(std::move(s));
    }
    std::sort(result.stations.begin(), result.stations.end(),
              [](const Station& a, const Station& b) { return a.id < b.id; });
    if (result.stations.size() < 3)
        fail(factoryFile, "stations", "line needs at least three stations");
    for (std::size_t i = 0; i < result.stations.size(); ++i)
        if (result.stations[i].id != i)
            fail(factoryFile, "stations", "IDs must be contiguous from 0");
    if (!result.stations.front().isSource || !result.stations.back().isSink)
        fail(factoryFile, "stations", "first station must be source and last station must be sink");
    std::set<std::string> checkpointIds;
    for (const auto& item : factory.value("checkpoints", json::array()))
    {
        CheckpointConfig c{item.at("stationId"),
                           item.at("id"),
                           item.at("type"),
                           item.at("progress"),
                           item.at("reliability"),
                           item.value("falsePositiveRate", 0.0),
                           item.value("identifiesUnit", true)};
        if (!ids.contains(c.stationId) || !checkpointIds.insert(c.id).second || c.progress <= 0 ||
            c.progress >= 1 || (c.type != "RFID" && c.type != "POWER_DRAW"))
            fail(factoryFile, "checkpoint " + c.id, "invalid definition");
        probability(factoryFile, "checkpoint " + c.id + ".reliability", c.reliability);
        probability(factoryFile, "checkpoint " + c.id + ".falsePositiveRate", c.falsePositiveRate);
        result.checkpoints.push_back(std::move(c));
    }
    if (scenario.contains("darkZones"))
        fail(scenarioFile, "darkZones", "belongs in factory.json");
    StationId previousEnd = 0;
    bool first = true;
    std::set<std::string> zoneIds;
    for (const auto& item : factory.value("darkZones", json::array()))
    {
        const auto& o = item.at("observability");
        DarkZoneConfig z{item.at("id"),
                         item.at("name"),
                         item.at("startStationId"),
                         item.at("endStationId"),
                         {o.value("sensorTelemetry", false), o.value("manualChecks", false),
                          o.value("checkpoints", false)}};
        if (!zoneIds.insert(z.id).second || !ids.contains(z.startStationId) ||
            !ids.contains(z.endStationId) || z.startStationId >= z.endStationId ||
            z.startStationId == 0 || z.endStationId + 1 >= result.stations.size() ||
            (!first && z.startStationId <= previousEnd + 1))
            fail(factoryFile, "dark zone " + z.id,
                 "must be an internal, non-adjacent group of at least two stations");
        for (StationId n = z.startStationId; n <= z.endStationId; ++n)
            if (result.stations[n].archetype == "INSPECTION")
                fail(factoryFile, "dark zone " + z.id,
                     "inspection stations are not supported inside a dark zone");
        previousEnd = z.endStationId;
        first = false;
        result.darkZones.push_back(std::move(z));
    }
    for (const auto& item : scenario.value("degradation", json::array()))
    {
        DegradationConfig d{item.at("stationId"), item.at("scenario"),
                            item.value("initialLevel", 0.0)};
        if (!ids.contains(d.stationId) || !validDegradation(d.scenario))
            fail(scenarioFile, "degradation", "invalid station or scenario");
        probability(scenarioFile, "degradation.initialLevel", d.initialLevel);
        result.degradation.push_back(std::move(d));
    }
    std::set<std::string> types;
    for (const auto& item : defects.at("defects"))
    {
        DefectDefinitionConfig d{item.at("type"),
                                 item.at("introductionStations"),
                                 item.at("baseProbability"),
                                 item.value("degradationSensitivity", 0.0),
                                 {}};
        if (!types.insert(d.type).second || d.introductionStations.empty() ||
            d.degradationSensitivity < 0)
            fail(defectsFile, "defect " + d.type, "duplicate, empty, or negative sensitivity");
        probability(defectsFile, "defect " + d.type + ".baseProbability", d.baseProbability);
        for (auto id : d.introductionStations)
            if (!ids.contains(id))
                fail(defectsFile, "defect " + d.type, "introduction station does not exist");
        for (const auto& itemEffect : item.value("effects", json::array()))
        {
            DefectEffectConfig e{};
            e.stationId = itemEffect.at("stationId");
            e.cycleTimeMultiplier = itemEffect.value("cycleTimeMultiplier", 1.0);
            e.extraCV = itemEffect.value("extraCV", 0.0);
            if (itemEffect.contains("sensorEffects"))
                for (auto it = itemEffect["sensorEffects"].begin();
                     it != itemEffect["sensorEffects"].end(); ++it)
                    e.sensorMeanShifts[it.key()] = it.value().at("meanShift").get<double>();
            if (itemEffect.contains("manualCheckEffects"))
                for (const auto& c : itemEffect["manualCheckEffects"])
                {
                    auto p = c.at("failProbability").get<double>();
                    probability(defectsFile, "manualCheckEffects.failProbability", p);
                    e.manualCheckFailProbabilities[c.at("measurement")] = p;
                }
            if (itemEffect.contains("inspection"))
            {
                e.inspectionDetectionProbability =
                    itemEffect["inspection"].at("detectionProbability");
                e.inspectionSeverity = itemEffect["inspection"].at("severity");
                probability(defectsFile, "inspection.detectionProbability",
                            e.inspectionDetectionProbability);
                if (e.inspectionSeverity < 1)
                    fail(defectsFile, "inspection.severity", "must be positive");
            }
            if (!ids.contains(e.stationId) || e.cycleTimeMultiplier <= 0 || e.extraCV < 0)
                fail(defectsFile, "defect effect", "invalid station or cycle-time effect");
            d.effects.push_back(std::move(e));
        }
        result.defects.push_back(std::move(d));
    }
    return result;
}

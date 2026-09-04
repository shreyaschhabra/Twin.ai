#include "Output.hpp"

#include <iomanip>
#include <sstream>
#include <stdexcept>

OutputWriter::OutputWriter(const std::filesystem::path& outputDirectory)
    : outputDirectory(outputDirectory)
{
    std::filesystem::create_directories(outputDirectory);
    unitsFile.open(outputDirectory / "units.csv");
    stationEventsFile.open(outputDirectory / "station_events.csv");
    sensorReadingsFile.open(outputDirectory / "sensor_readings.csv");
    manualChecksFile.open(outputDirectory / "manual_checks.csv");
    inspectionResultsFile.open(outputDirectory / "inspection_results.csv");
    checkpointEventsFile.open(outputDirectory / "checkpoint_events.csv");
    runtimeEventsFile.open(outputDirectory / "runtime_events.csv");

    if (!unitsFile || !stationEventsFile || !sensorReadingsFile || !manualChecksFile ||
        !inspectionResultsFile || !checkpointEventsFile || !runtimeEventsFile)
    {
        throw std::runtime_error("Failed to open output files");
    }

    unitsFile << "unit_id,"
              << "created_at_ms,"
              << "vehicle_model,"
              << "supplier_batch\n";

    stationEventsFile << "event_id,"
                      << "timestamp_ms,"
                      << "event_type,"
                      << "station_id,"
                      << "unit_id,"
                      << "queue_length_after,"
                      << "previous_state,"
                      << "new_state,"
                      << "cycle_time_ms,dark_zone_id\n";

    sensorReadingsFile << "timestamp_ms,station_id,sensor_type,value,unit\n";
    manualChecksFile << "timestamp_ms,station_id,unit_id,check_type,result\n";
    inspectionResultsFile << "timestamp_ms,station_id,unit_id,defect_type,severity,result\n";
    checkpointEventsFile << "event_id,timestamp_ms,event_type,station_id,unit_id,checkpoint_id\n";
    runtimeEventsFile << "sequence,timestamp_ms,record_type,event_id,event_type,station_id,unit_id,"
                      << "queue_length_after,previous_state,new_state,cycle_time_ms,dark_zone_id,checkpoint_id,"
                      << "sensor_type,sensor_value,sensor_unit,check_type,check_result\n";

    // These two files are tailed/read while the simulator is still running.
    // Make their schemas visible immediately, before the first unit/event arrives.
    unitsFile.flush();
    runtimeEventsFile.flush();
}

void OutputWriter::close()
{
    unitsFile.close();
    stationEventsFile.close();
    sensorReadingsFile.close();
    manualChecksFile.close();
    inspectionResultsFile.close();
    checkpointEventsFile.close();
    runtimeEventsFile.close();
}

namespace
{

std::string stationKey(StationId id)
{
    std::ostringstream stream;
    stream << 'S' << std::setw(2) << std::setfill('0') << id + 1;
    return stream.str();
}

std::string unitKey(UnitId id)
{
    std::ostringstream stream;
    stream << 'U' << std::setw(6) << std::setfill('0') << id;
    return stream.str();
}

std::string eventKey(std::uint64_t id)
{
    std::ostringstream stream;
    stream << "EV" << std::setw(6) << std::setfill('0') << id;
    return stream.str();
}

std::string toString(StationState state)
{
    switch (state)
    {
        case StationState::IDLE:
            return "IDLE";

        case StationState::PROCESSING:
            return "PROCESSING";

        case StationState::BLOCKED:
            return "BLOCKED";

        case StationState::STARVED:
            return "STARVED";
    }

    return "";
}

std::string toString(StationEventType type)
{
    switch (type)
    {
        case StationEventType::UNIT_ARRIVED:
            return "UNIT_ARRIVED";

        case StationEventType::PROCESSING_STARTED:
            return "PROCESSING_STARTED";

        case StationEventType::PROCESSING_COMPLETED:
            return "PROCESSING_COMPLETED";

        case StationEventType::STATE_CHANGED:
            return "STATE_CHANGED";
        case StationEventType::DARK_ZONE_ENTERED:
            return "DARK_ZONE_ENTERED";
        case StationEventType::DARK_ZONE_EXITED:
            return "DARK_ZONE_EXITED";
    }

    return "";
}

}  // namespace

void OutputWriter::writeStationCheckpoints(const std::vector<CheckpointDefinition>& checkpoints)
{
    std::ofstream file(outputDirectory / "station_checkpoints.csv");
    if (!file)
        throw std::runtime_error("Failed to open station_checkpoints.csv");

    file << "station_id,checkpoint_id,checkpoint_type,nominal_progress_fraction,"
         << "read_reliability,false_positive_rate,identifies_unit\n";
    for (const CheckpointDefinition& checkpoint : checkpoints)
    {
        file << stationKey(checkpoint.stationId) << ',' << checkpoint.checkpointId << ','
             << checkpoint.checkpointType << ',' << checkpoint.nominalProgressFraction << ','
             << checkpoint.readReliability << ',' << checkpoint.falsePositiveRate << ','
             << (checkpoint.identifiesUnit ? "true" : "false") << '\n';
    }
}

void OutputWriter::writeDarkZones(const std::vector<DarkZoneConfig>& zones)
{
    std::ofstream file(outputDirectory / "dz.csv");
    if (!file)
        throw std::runtime_error("Failed to open dz.csv");

    file << "dark_zone_id,name,start_station_id,end_station_id,sensor_telemetry,manual_checks,checkpoints\n";
    for (const DarkZoneConfig& zone : zones)
        file << zone.id << ',' << zone.name << ',' << stationKey(zone.startStationId) << ','
             << stationKey(zone.endStationId) << ','
             << (zone.observability.sensorTelemetry ? "true" : "false") << ','
             << (zone.observability.manualChecks ? "true" : "false") << ','
             << (zone.observability.checkpoints ? "true" : "false") << '\n';
}

void OutputWriter::writeStations(const std::vector<Station>& stations)
{
    std::ofstream file(outputDirectory / "stations.csv");

    if (!file)
    {
        throw std::runtime_error("Failed to open stations.csv");
    }

    file << "station_id,"
         << "name,"
         << "archetype,"
         << "base_cycle_time_ms,"
         << "cycle_time_std_ms,"
         << "buffer_capacity,"
         << "sensor_coverage\n";

    for (const Station& station : stations)
    {
        file << stationKey(station.id) << ',' << station.name << ',' << station.archetype << ','
             << station.meanCycleTime << ','
             << static_cast<Time>(station.meanCycleTime * station.cycleTimeCV) << ','
             << station.bufferCapacity << ',' << station.sensorCoverage << '\n';
    }
}

void OutputWriter::writeUnit(UnitId unitId, Time createdAt)
{
    const std::string model = unitId % 5 == 0 ? "MODEL_B" : "MODEL_A";
    const std::string batch = unitId % 7 == 0 ? "BATCH_02" : "BATCH_01";
    unitsFile << unitKey(unitId) << ',' << createdAt << ',' << model << ',' << batch << '\n';
    unitsFile.flush();
}

void OutputWriter::writeStationEvent(const StationEvent& event)
{
    const std::string id = eventKey(nextEventId++);
    stationEventsFile << id << ',' << event.timestamp << ','
                      << toString(event.type) << ',' << stationKey(event.stationId) << ',';

    const std::string unit = event.unitId.has_value() ? unitKey(*event.unitId) : "";
    if (!unit.empty()) stationEventsFile << unit;
    stationEventsFile << ',';
    if (event.queueLengthAfter.has_value()) stationEventsFile << *event.queueLengthAfter;
    stationEventsFile << ',';
    if (event.previousState.has_value()) stationEventsFile << toString(*event.previousState);
    stationEventsFile << ',';
    if (event.newState.has_value()) stationEventsFile << toString(*event.newState);
    stationEventsFile << ',';
    if (event.cycleTime.has_value()) stationEventsFile << *event.cycleTime;
    stationEventsFile << ',';
    if (event.darkZoneId.has_value()) stationEventsFile << *event.darkZoneId;
    stationEventsFile << '\n';

    runtimeEventsFile << nextRuntimeSequence++ << ',' << event.timestamp << ",STATION," << id << ','
                      << toString(event.type) << ',' << stationKey(event.stationId) << ',' << unit << ',';
    if (event.queueLengthAfter.has_value()) runtimeEventsFile << *event.queueLengthAfter;
    runtimeEventsFile << ',';
    if (event.previousState.has_value()) runtimeEventsFile << toString(*event.previousState);
    runtimeEventsFile << ',';
    if (event.newState.has_value()) runtimeEventsFile << toString(*event.newState);
    runtimeEventsFile << ',';
    if (event.cycleTime.has_value()) runtimeEventsFile << *event.cycleTime;
    runtimeEventsFile << ',';
    if (event.darkZoneId.has_value()) runtimeEventsFile << *event.darkZoneId;
    runtimeEventsFile << ",,,,,,\n";
    runtimeEventsFile.flush();
}

void OutputWriter::writeCheckpointEvent(Time timestamp, const std::string& eventType,
                                        StationId stationId, std::optional<UnitId> unitId,
                                        const std::string& checkpointId)
{
    std::ostringstream idStream;
    idStream << "CE" << std::setw(6) << std::setfill('0') << nextCheckpointEventId++;
    const std::string id = idStream.str();
    const std::string unit = unitId ? unitKey(*unitId) : "";
    checkpointEventsFile << id << ',' << timestamp << ',' << eventType << ',' << stationKey(stationId)
                         << ',' << unit << ',' << checkpointId << '\n';

    runtimeEventsFile << nextRuntimeSequence++ << ',' << timestamp << ",EVIDENCE," << id << ','
                      << eventType << ',' << stationKey(stationId) << ',' << unit
                      << ",,,,,," << checkpointId << ",,,,,\n";
    runtimeEventsFile.flush();
}

void OutputWriter::writeSensorReading(Time timestamp, StationId stationId,
                                      const std::string& sensorType, double value,
                                      const std::string& unit)
{
    sensorReadingsFile << timestamp << ',' << stationKey(stationId) << ',' << sensorType << ','
                       << value << ',' << unit << '\n';

    // SENSOR is public telemetry, not hidden station-state truth. It is intentionally
    // present in DARK zones only when the ObservationPolicy allows sensor telemetry.
    runtimeEventsFile << nextRuntimeSequence++ << ',' << timestamp
                      << ",SENSOR,,SENSOR_READING," << stationKey(stationId)
                      << ",,,,,,,," << sensorType << ',' << value << ',' << unit << ",,\n";
    runtimeEventsFile.flush();
}

void OutputWriter::writeManualCheck(Time timestamp, StationId stationId,
                                    std::optional<UnitId> unitId, const std::string& checkType,
                                    const std::string& result)
{
    manualChecksFile << timestamp << ',' << stationKey(stationId) << ',';
    const std::string unitIdText = unitId ? unitKey(*unitId) : "";
    if (unitId)
        manualChecksFile << unitIdText;
    manualChecksFile << ',' << checkType << ',' << result << '\n';

    // Manual observations are also causal public evidence. They may remain visible
    // in a DARK zone when the factory's observability policy explicitly permits them.
    runtimeEventsFile << nextRuntimeSequence++ << ',' << timestamp
                      << ",MANUAL,,MANUAL_CHECK," << stationKey(stationId) << ',' << unitIdText
                      << ",,,,,,,,,," << checkType << ',' << result << '\n';
    runtimeEventsFile.flush();
}

void OutputWriter::writeInspectionResult(Time timestamp, StationId stationId, UnitId unitId,
                                         const std::string& defectType, std::optional<int> severity,
                                         const std::string& result)
{
    inspectionResultsFile << timestamp << ',' << stationKey(stationId) << ',' << unitKey(unitId)
                          << ',' << defectType << ',';
    if (severity.has_value())
        inspectionResultsFile << *severity;
    inspectionResultsFile << ',' << result << '\n';
}

void OutputWriter::writeRunMetadata(const std::string& runId, std::uint32_t randomSeed,
                                    Time duration, std::size_t stationCount, UnitId unitsCreated)
{
    std::ofstream file(outputDirectory / "run_metadata.json");
    if (!file)
        throw std::runtime_error("Failed to open run_metadata.json");

    file << "{\n"
         << "  \"run_id\": \"" << runId << "\",\n"
         << "  \"random_seed\": " << randomSeed << ",\n"
         << "  \"simulation_duration_ms\": " << duration << ",\n"
         << "  \"station_count\": " << stationCount << ",\n"
         << "  \"units_created\": " << unitsCreated << ",\n"
         << "  \"schema_version\": \"2.1\"\n}\n";
}

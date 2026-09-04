cmake_policy(SET CMP0007 NEW)

if(NOT DEFINED SIMULATOR OR NOT DEFINED FACTORY OR NOT DEFINED DEFECTS OR NOT DEFINED SCENARIO_A OR NOT DEFINED SCENARIO_B OR NOT DEFINED TEST_OUTPUT)
    message(FATAL_ERROR "Integration test inputs are required")
endif()

file(REMOVE_RECURSE "${TEST_OUTPUT}")

function(run_simulation scenario output)
    execute_process(
        COMMAND "${SIMULATOR}" --factory "${FACTORY}" --scenario "${scenario}" --defects "${DEFECTS}" --output "${output}"
        RESULT_VARIABLE result
        OUTPUT_VARIABLE stdout
        ERROR_VARIABLE stderr)
    if(NOT result EQUAL 0)
        message(FATAL_ERROR "Simulator failed: ${stdout}${stderr}")
    endif()
endfunction()

run_simulation("${SCENARIO_A}" "${TEST_OUTPUT}/run_a")
run_simulation("${SCENARIO_B}" "${TEST_OUTPUT}/run_b")

set(required_files stations.csv units.csv station_events.csv sensor_readings.csv manual_checks.csv inspection_results.csv checkpoint_events.csv station_checkpoints.csv runtime_events.csv dz.csv)
foreach(file IN LISTS required_files)
    if(NOT EXISTS "${TEST_OUTPUT}/run_a/${file}" OR NOT EXISTS "${TEST_OUTPUT}/run_b/${file}")
        message(FATAL_ERROR "Missing required run output: ${file}")
    endif()
endforeach()

file(READ "${TEST_OUTPUT}/run_a/runtime_events.csv" runtime_events)
string(FIND "${runtime_events}" "sequence,timestamp_ms,record_type,event_id,event_type" runtime_header)
string(FIND "${runtime_events}" ",STATION," runtime_station)
string(FIND "${runtime_events}" ",EVIDENCE," runtime_evidence)
if(runtime_header EQUAL -1 OR runtime_station EQUAL -1 OR runtime_evidence EQUAL -1)
    message(FATAL_ERROR "runtime_events.csv must contain ordered STATION and EVIDENCE records")
endif()

# The public bus is consumed live by run_current.py.  Sequence must be contiguous
# and timestamps must never move backward; otherwise late checkpoint evidence
# would violate causal replay even if the final CSV contained all records.
file(STRINGS "${TEST_OUTPUT}/run_a/runtime_events.csv" runtime_lines)
list(POP_FRONT runtime_lines runtime_header_line)
set(last_sequence 0)
set(last_timestamp -1)
foreach(line IN LISTS runtime_lines)
    if(line STREQUAL "")
        continue()
    endif()
    string(REPLACE "," ";" fields "${line}")
    list(GET fields 0 sequence)
    list(GET fields 1 timestamp)
    math(EXPR expected_sequence "${last_sequence} + 1")
    if(NOT sequence EQUAL expected_sequence)
        message(FATAL_ERROR "runtime_events.csv sequence is not contiguous at ${sequence}")
    endif()
    if(timestamp LESS last_timestamp)
        message(FATAL_ERROR "runtime_events.csv timestamp moved backward at sequence ${sequence}")
    endif()
    set(last_sequence ${sequence})
    set(last_timestamp ${timestamp})
endforeach()

file(READ "${TEST_OUTPUT}/run_a/dz.csv" dz)
string(FIND "${dz}" "DZ_BODY_01,Legacy Body Alignment Section,S12,S15,true,true,true" dz_index)
if(dz_index EQUAL -1)
    message(FATAL_ERROR "dz.csv does not describe the factory DARK zone")
endif()

file(READ "${TEST_OUTPUT}/run_a/run_metadata.json" metadata_a)
file(READ "${TEST_OUTPUT}/run_b/run_metadata.json" metadata_b)
if(NOT metadata_a MATCHES "\"random_seed\": 42" OR NOT metadata_b MATCHES "\"random_seed\": 99")
    message(FATAL_ERROR "Independent scenarios did not retain their own configuration")
endif()

file(WRITE "${TEST_OUTPUT}/scenario_with_dark_zone.json"
    "{\"randomSeed\":1,\"durationMs\":1000,\"darkZones\":[]}")
execute_process(
    COMMAND "${SIMULATOR}" --factory "${FACTORY}" --scenario "${TEST_OUTPUT}/scenario_with_dark_zone.json" --defects "${DEFECTS}" --output "${TEST_OUTPUT}/invalid_scenario"
    RESULT_VARIABLE scenario_result
    ERROR_VARIABLE scenario_error)
if(scenario_result EQUAL 0 OR NOT scenario_error MATCHES "darkZones.*belongs in factory.json")
    message(FATAL_ERROR "Scenario-level DARK zones were not rejected")
endif()

execute_process(
    COMMAND "${SIMULATOR}" --config "${TEST_OUTPUT}/obsolete.zip" --output "${TEST_OUTPUT}/obsolete"
    RESULT_VARIABLE zip_result)
if(zip_result EQUAL 0)
    message(FATAL_ERROR "Obsolete ZIP CLI was accepted")
endif()

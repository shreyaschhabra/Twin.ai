cmake_minimum_required(VERSION 3.20)

project(DigitalTwinSimulation)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

include(FetchContent)
FetchContent_Declare(nlohmann_json
    GIT_REPOSITORY https://github.com/nlohmann/json.git
    GIT_TAG v3.11.3
    GIT_SHALLOW TRUE
)
FetchContent_MakeAvailable(nlohmann_json)

add_executable(simulation
    src/main.cpp
    src/Simulation.cpp
    src/Output.cpp
    src/ConfigLoader.cpp
    src/ObservationPolicy.cpp
)

target_link_libraries(simulation PRIVATE nlohmann_json::nlohmann_json)

add_custom_command(TARGET simulation POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_directory
        ${CMAKE_CURRENT_SOURCE_DIR}/config $<TARGET_FILE_DIR:simulation>/config)

include(CTest)
if(BUILD_TESTING)
    add_test(NAME simulator_filesystem_workflow
        COMMAND ${CMAKE_COMMAND}
            -DSIMULATOR=$<TARGET_FILE:simulation>
            -DFACTORY=${CMAKE_CURRENT_SOURCE_DIR}/config/factory.json
            -DDEFECTS=${CMAKE_CURRENT_SOURCE_DIR}/config/defects.json
            -DSCENARIO_A=${CMAKE_CURRENT_SOURCE_DIR}/config/scenarios/baseline.json
            -DSCENARIO_B=${CMAKE_CURRENT_SOURCE_DIR}/config/scenarios/degradation.json
            -DTEST_OUTPUT=${CMAKE_CURRENT_BINARY_DIR}/integration-output
            -P ${CMAKE_CURRENT_SOURCE_DIR}/tests/FilesystemWorkflow.cmake)
endif()

#pragma once

#include <filesystem>

#include "Config.hpp"

class ConfigLoader
{
   public:
    static SimulationConfig load(const std::filesystem::path& factoryFile,
                                 const std::filesystem::path& scenarioFile,
                                 const std::filesystem::path& defectsFile);
};

#include <filesystem>
#include <iostream>

#include "ConfigLoader.hpp"
#include "Simulation.hpp"

int main(int argc, char** argv)
{
    try
    {
        std::filesystem::path factory = "config/factory.json";
        std::filesystem::path scenario = "config/scenarios/degradation.json";
        std::filesystem::path defects = "config/defects.json";
        std::filesystem::path output = "output/run_001";

        for (int i = 1; i < argc; ++i)
        {
            const std::string argument = argv[i];
            if (argument == "--factory" && i + 1 < argc)
            {
                factory = argv[++i];
            }
            else if (argument == "--scenario" && i + 1 < argc)
            {
                scenario = argv[++i];
            }
            else if (argument == "--defects" && i + 1 < argc)
            {
                defects = argv[++i];
            }
            else if (argument == "--output" && i + 1 < argc)
            {
                output = argv[++i];
            }
            else if (argument == "--help")
            {
                std::cout << "simulation --factory FACTORY.json --scenario SCENARIO.json "
                             "--defects DEFECTS.json --output RUN_DIRECTORY\\n";
                return 0;
            }
            else
            {
                throw std::runtime_error("unknown or incomplete argument: " + argument);
            }
        }

        const std::string runName = scenario.stem().string();
        Simulation simulation(ConfigLoader::load(factory, scenario, defects), output, runName);
        simulation.run();
    }
    catch (const std::exception& error)
    {
        std::cerr << error.what() << '\\n';
        return 1;
    }
}

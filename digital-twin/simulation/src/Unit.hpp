#pragma once

#include <cstdint>
#include <string>
#include <vector>

using UnitId = std::uint64_t;

struct UnitDefect
{
    std::string type;
    std::uint32_t introducedAtStation;
    std::int64_t introducedAt;
};

struct Unit
{
    UnitId id;
    std::string vehicleModel;
    std::string supplierBatch;
    std::vector<UnitDefect> defects;
};

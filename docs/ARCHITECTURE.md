# TrustTwin - Architecture

TrustTwin follows a unidirectional data flow architecture designed to enforce a strict separation between physical reality (the factory simulation) and the software systems monitoring it (the digital twin).

## Layer 1: Physical Reality (`backend.simulation`)
This layer represents the absolute ground truth of the factory floor.
- **Engine**: A discrete-event simulation built with SimPy.
- **Physics**: Accurately models vehicle movement, station processing times, buffer capacities, and equipment degradation scenarios.
- **Output**: An internal event stream containing perfect, omniscient knowledge of every vehicle, station, and buffer state.
- **Constraint**: The intelligence layer must NEVER access this layer directly.

## Layer 2: Observability Policy (`backend.observability`)
This layer models the limitations of a real-world IoT sensor network.
- **Filter**: Takes the omniscient internal event stream and filters it down to a `PublicEvent` stream.
- **Degradation**: Applies noise, dropouts, and delays based on configured sensor maturities (RICH, PARTIAL, POOR).
- **Output**: A realistic, imperfect stream of telemetry that a digital twin would actually receive.

## Layer 3: Intelligence (`backend.intelligence`)
This is the core of the digital twin, consuming only the `PublicEvent` stream to infer the actual state of the factory and predict future issues.
- **TrustService**: Validates incoming sensor data, handling dropouts by falling back to historical medians or spatial averages (same-type stations), outputting data states as LIVE, INFERRED, or UNKNOWN.
- **FlowService**: Uses LightGBM regression to predict service deterioration based on subtle precursor metrics (cycle time trends, micro-stops), then uses physics to project `time_to_blocking` and assign a `riskLevel`.
- **QualityService**: Uses LightGBM classification to predict the probability of a defective vehicle based on its progression through the factory.
- **AnomalyService**: Uses an Isolation Forest to flag broader operational deviations that don't fit the expected healthy factory profile.

## Layer 4: Application (To Be Built)
The FastAPI server and frontend dashboard that present the intelligence layer's findings to the user.

# Bike Safety Computer

An exploratory bicycle computer concept built around a Raspberry Pi 5. The goal
is to combine cycling sensors, environmental measurements, GPS, and forward- or
rear-facing cameras in a single device that mounts on a bicycle like a
conventional Garmin head unit.

The longer-term research direction is to use these data to recognize road
conditions and estimate the risk of hazardous road segments, then present useful
safety information to the rider.

## Concept

The device is envisioned as an enhanced, extensible alternative to a standard
bicycle computer:

- receive live data from bicycle sensors over ANT+;
- record GPS position and ride data;
- measure local temperature, pressure, and humidity;
- capture the road ahead and, optionally, the scene behind the bicycle;
- combine sensor, location, and image data for road-safety analysis;
- fit into a compact, 3D-printed enclosure compatible with a Garmin-style bike
  mount.

## Planned Hardware

| Component | Intended role |
| --- | --- |
| Raspberry Pi 5 | Main computing platform |
| USB ANT+ dongle | Connect to compatible bicycle sensors |
| ANT+ sensors | Speed, cadence, and power measurements |
| SRAM drivetrain | Explore access to electronic shifting data, subject to protocol and hardware compatibility |
| Garmin Varia radar | Detect and report approaching vehicles, subject to integration testing |
| GPS receiver | Record position and ride trajectory |
| BME280 | Measure temperature, barometric pressure, and humidity |
| One or two cameras | Observe the road ahead and optionally behind the saddle |
| 3D-printed enclosure | Protect and mount the electronics on a Garmin-style bike mount |

The hardware list describes the intended prototype. Component selection,
interfaces, power, weather protection, and mechanical fit remain to be validated.

## Intended Data and Analysis

The system could combine:

- rider and bicycle telemetry, such as speed, cadence, power, and gear changes;
- GPS position and route history;
- environmental context from the BME280;
- visual observations from the front and optional rear cameras;
- nearby-vehicle information from a compatible radar.

The longer-term objective is to explore road-hazard prediction from these
signals. The project is at the concept stage: no sensor integration, prediction
model, or finished device is claimed to be implemented yet.

## Development Outline

1. Validate ANT+ reception for the selected sensors.
2. Establish GPS and environmental data logging.
3. Prototype camera capture and timestamp alignment across data sources.
4. Design and print an enclosure for the electronics and bike mount.
5. Collect ride data and investigate methods for identifying risky road
   conditions.
6. Develop a rider-facing display and evaluate it during controlled rides.

## Status

This repository documents and will host the initial prototype. Hardware,
software, mounting, and safety-analysis plans are exploratory and may change as
compatibility and field testing inform the design.

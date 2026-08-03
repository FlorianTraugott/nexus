# Project Aurora — Technical Architecture

This document describes the main components of the Aurora microgrid and how they
fit together. All figures are nameplate ratings unless noted otherwise.

## Generation

- Solar PV array: 3.0 MW of ground-mounted panels across 6 hectares.
- Combined heat-and-power (CHP) backup generator: 1.2 MW, natural-gas fuelled,
  used only when solar and storage cannot meet demand.

## Storage

- Battery: 8 MWh lithium iron phosphate (LFP) pack.
- Usable depth of discharge: 90 percent.
- Round-trip efficiency: 92 percent.

LFP chemistry was chosen over standard lithium-ion for its thermal stability and
longer cycle life, which matters for a system that charges and discharges daily.

## Power electronics

- Grid-forming inverters with a rated conversion efficiency of 98.2 percent.
- The inverters allow Aurora to run grid-tied or to island automatically within
  20 milliseconds of detecting a grid fault.

## Control

A local controller balances generation, storage, and load every second. Its
priority order during an outage is: (1) critical-facilities circuit, (2) battery
preservation above 20 percent state of charge, (3) general residential load.

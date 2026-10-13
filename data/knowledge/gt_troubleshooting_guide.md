# Gas Turbine Condition Troubleshooting Guide (SYNTHETIC, for demo only)

This guide was written for the FaultLens hackathon demo. It is not from any manufacturer or utility and must not be used on real equipment. Sensor codes follow the NASA C-MAPSS naming used in the demo data.

## [MAN-01] Safety and use of this guide
All inspection and maintenance work requires a valid permit to work and lock-out/tag-out of the unit. Never bypass, disable or override a protection, trip or interlock to keep a unit running. Diagnostic suggestions are advisory and must be confirmed by a qualified technician before any intervention. When a symptom is not described in this guide, stop and escalate to the reliability engineer.

## [MAN-02] HPC degradation signature (compressor fouling or erosion)
Typical pattern: total temperatures at LPC outlet (T24), HPC outlet (T30) and LPT outlet (T50) rise gradually together; total pressure at HPC outlet (P30) falls; static pressure Ps30 rises; core speed (Nc, NRc) and fan speed (Nf, NRf) drift upward as control compensates; HPT and LPT coolant bleed (W31, W32) fall. The change develops over many cycles rather than in a single step.
Most common cause: fouling of compressor blades by airborne contaminants, reducing compressor efficiency. Less common: blade tip erosion.
First actions: check inlet air filter differential pressure and filter condition; review the date of the last compressor wash; perform an online compressor wash if the trend is early; schedule an offline (crank) wash at the next planned stop. If the trend continues after washing, request a borescope inspection of the HPC stages to check for erosion or damage.

## [MAN-03] Hot section degradation
Typical pattern: LPT outlet temperature (T50) rises faster than T30; exhaust temperature spread between thermocouples widens; coolant bleed (W31, W32) may fall.
Likely causes: combustor liner or fuel nozzle deterioration, turbine blade coating loss, or restricted cooling passages.
First actions: compare individual exhaust thermocouple readings to find a hot spot; inspect fuel nozzles at the next stop; request a hot gas path borescope inspection. A rapidly widening exhaust spread requires escalation.

## [MAN-04] Compressor outlet pressure loss with stable temperatures
Typical pattern: P30 falls and the engine pressure ratio drops while T30 stays near normal.
Likely causes: bleed valve stuck partly open, inlet guide vane (IGV) angle out of calibration, or an air leak at the compressor discharge casing.
First actions: check bleed valve position feedback against command; verify IGV calibration; perform a leak check on compressor discharge flanges during the next stop.

## [MAN-05] Shaft speed drift and bearing concerns
Typical pattern: physical core speed (Nc) or fan speed (Nf) drifts without a matching change in load demand, or corrected speeds (NRc, NRf) diverge from demand.
Likely causes: control loop compensation for efficiency loss (see MAN-02), or mechanical issues such as bearing wear.
First actions: compare speed drift with the HPC degradation signature first. If temperatures and pressures are normal, review vibration trends and take a lube oil sample for wear metal analysis. Any rise in bearing vibration requires escalation.

## [MAN-06] Bleed enthalpy and bypass ratio changes
Typical pattern: bleed enthalpy (htBleed) and bypass ratio (BPR) rise together.
Likely causes: often a secondary effect of compressor efficiency loss (MAN-02). If seen alone, suspect a bleed valve or actuator fault.
First actions: inspect bleed valve actuators and position feedback; confirm whether MAN-02 signature is also present before replacing parts.

## [MAN-07] Falling turbine coolant bleed flow (W31, W32)
Typical pattern: HPT coolant bleed (W31) and LPT coolant bleed (W32) fall over time.
Risk: reduced cooling air increases turbine blade metal temperature and can shorten blade life.
First actions: if seen together with the MAN-02 signature, treat compressor fouling as the probable root cause and plan a wash. If W31 or W32 falls alone or falls quickly, suspect a blockage in the cooling air path and escalate to the reliability engineer before continued operation.

## [MAN-08] Instrumentation fault or real degradation?
Signs of an instrument fault: a sudden step change in one sensor while related sensors do not move; readings that freeze at a constant value; noise much larger than usual; disagreement between redundant sensors.
Signs of real degradation: gradual trends over many cycles; several physically related sensors moving in a consistent direction.
First actions: compare with redundant or related sensors; check the sensor calibration record; if a single sensor is suspect, raise an instrumentation work order before any mechanical intervention.

## [MAN-09] Escalation criteria
Escalate to the reliability engineer when any of the following applies: the condition is rated critical; predicted remaining life is low enough that the unit may not reach the next planned stop; the pattern is not described in this guide; signals conflict and no single cause fits; coolant flow drops quickly (MAN-07); bearing vibration rises (MAN-05). The engineer decides on load reduction or shutdown. Technicians must not reduce protection settings.

## [MAN-10] Work order standards
Priority P1: safety risk or risk of unplanned trip. Act within the current shift and notify the engineer.
Priority P2: degradation confirmed, plan work before the next planned stop.
Priority P3: monitoring or minor work at the next planned stop.
Every work order must state the asset, the observed symptoms, the suspected cause with its reference, the requested work, and the permit requirements.

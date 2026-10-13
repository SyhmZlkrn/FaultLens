# Demo video script (3 to 4 minutes)

## 0:00 Problem (30 s)
Show INC-2026-003: the fouling trend was visible about 50 cycles early, but it was found late and became a 31 hour forced outage instead of a 9 hour planned wash (INC-2025-004). Who suffers: the shift technician and the reliability engineer.

## 0:30 Healthy unit (20 s)
Pick a unit, slider early. Status NORMAL, Diagnose button disabled. "It stays quiet when nothing is wrong."

## 0:50 Degrading unit (90 s)
Move slider forward until WARNING. Show the chart: T30 and T50 rising, P30 falling.
Click Diagnose. Walk through: summary, causes with citations, actions in order, uncertainties.
Open "Evidence used" to show it is reading the manual and past incidents.

## 2:20 Critical and guardrails (40 s)
Move to near end of life. Show forced escalation and P1 work order.
Open "Checks": verifier result and guardrail notes. "The model proposes, code enforces, a person approves."
Edit the work order, enter a name, approve.

## 3:00 AMD (30 s)
Sidebar AMD panel: the reasoning model served by AMD Token Factory, its measured latency, and the model that answered. Open "Checks" to show the two Token Factory calls (diagnosis and verifier) with tokens and latency.

## 3:30 Value (20 s)
Diagnosis in under a minute instead of a manual trend review. Earlier warning turns forced outages into planned work. Next step: connect to a real historian and CMMS.

# ClaimCheck 2.0 — Strategy Comparison Report

**Execution Timestamp:** `2026-10-23T17:49:07.005766+00:00`  

**Git Commit Hash:** `89004f4813d132d86fa37e025308ec32bb7666a9`  

**Packets Evaluated Per Strategy:** `2`


## Strategy Performance & Cost Summary Table

| Strategy | Model(s) | Fact Acc | Status Acc | False Warnings | Payout Acc | Citation Acc | p50 Latency | p95 Latency | Avg Cost/Packet | Total Cost |
|---|---|---|---|---|---|---|---|---|---|---|
| **ultra** | Nano-30B | 100.0% | 100.0% | 0.0% | 100.0% | 100.0% | 181.8 ms | 234.9 ms | $0.000145 | $0.000290 |
| **routed** | Nano-30B (Fast) + Super-120B (Reasoning) | 100.0% | 100.0% | 0.0% | 100.0% | 100.0% | 119.6 ms | 123.2 ms | $0.000145 | $0.000290 |

## Analysis & Architecture Trade-offs

- **Ultra Strategy:** Uses single fast model (`NVIDIA-Nemotron-3-Nano-30B-A3B`) for all extractions. Delivers low token overhead and minimal latency.
- **Routed Strategy:** Dynamically delegates complex claims (proportional room rent deductions, cataract sub-limits) to reasoning models (`Nemotron-3-Super-120B`), optimizing deduction accuracy where arithmetic reasoning is required.
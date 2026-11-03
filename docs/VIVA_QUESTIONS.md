# WASTEX — Viva / Mentor Questions & Answers

Short, defensible answers. Each one points to where the concept appears in the running system, so you can show it live.

---

## A. Problem and motivation

**Q1. What problem are you solving?**
Bengaluru collects waste on a fixed timetable (07:30–09:00 and 18:00–19:30), but every bin fills at a different and changing rate. Some bins overflow before the truck comes; others are emptied half-full. We turn live bin data into real-time decisions about **what** to collect, **when**, in **which order**, and with **which truck**.

**Q2. Why is this a *stream processing* problem and not batch analytics?**
Decisions depend on the *rate* of filling, which changes minute by minute (festivals, markets, matches). A fire or an overflow needs a reaction within minutes, not in tomorrow's report. One reading per bin per minute is a continuous, unbounded stream.

**Q3. What did the EDA tell you?**
- Growth rate matters more than level: 78% → 84% in 10 min overflows in about 27 min, before a slow 92% bin.
- Averages hide bins: Koramangala averaged 67% while one bin was at 91%.
- Plant capacity is uneven: 2,900 TPD capacity vs 1,150 TPD intake (40%). MSGP is at 83% and Kannahalli at 8%.
- Complaints concentrate in Bellandur (152) and Banaswadi (128).

**Q4. Which data is real and which is synthetic?**
- **Real:** ward locations, DWCCs, processing plants with capacities, landfills and complaint counts (BBMP / OpenCity).
- **Synthetic:** live fill, weight, temperature and battery readings, plus collection events. No city-wide smart-bin feed is public.
- The synthetic rates are calibrated to the EDA (0.2–0.6 %/min at peaks) and generated from a fixed seed (42), so results are reproducible.

## B. Kafka

**Q5. Why Kafka and not a database or REST calls?**
- Kafka decouples producers from consumers.
- It persists every event, so it can be replayed.
- It absorbs bursts (surges).
- Each service can scale as its own consumer group.
- Order is guaranteed per key.

With REST, a slow agent would block the sensors.

**Q6. What topics do you have and why those partition counts?**
- 8 topics, 28 partitions in total. `bin-telemetry` and `bin-analytics` have 6 partitions because they carry the highest volume.
- `agent-decisions` has **1** partition, so the decision log is totally ordered.
- Plans and fleet status are keyed by `truck_id`, so all messages for one truck stay in order.
- *Show:* the **Kafka Pipeline** page.

**Q7. How does a message choose a partition?**
`partition = murmur2(key) mod N`, Kafka's default partitioner, which we also implement in `bus.py` and in the Lab. Because the key is `bin_id`, every reading of a bin goes to the same partition, so the fill-rate calculation sees readings in order.
*Show:* **Kafka Lab** → Keyed vs Round-robin.

**Q8. What is a consumer group? What is lag?**
- A **consumer group** shares a topic's partitions: each partition is read by exactly one member.
- **Lag** = log-end offset − committed offset, i.e. how far behind the consumer is.
- Our 5 groups run at lag ≈ 0. *Show:* the consumer-group table.

**Q9. What happens if you add more consumers than partitions?**
The extra consumers sit idle. Partitions are the unit of parallelism. *Show:* the Lab with 5 consumers on 4 partitions; C5 is idle.

**Q10. What is a rebalance?**
When group membership changes, partitions are reassigned (we use the range assignor). Consumption pauses briefly. *Show:* the Lab → change "Consumers in group".

**Q11. What if a broker dies?**
Each partition has a leader and followers (RF = 3). The controller elects a new leader from the **ISR** (in-sync replicas). With `acks=all` and `min.insync.replicas=2`, no acknowledged data is lost. *Show:* the Lab → Kill a broker. Our Docker setup is a single broker (a laptop project), so replication is demonstrated in the Lab.

**Q12. acks=0 / 1 / all?**
- `acks=0`: fire-and-forget, fastest, can lose data.
- `acks=1`: the leader writes; data is lost only if the leader dies before followers copy it.
- `acks=all`: every in-sync replica acknowledges; safest. We use acks=1 for high-volume telemetry because a missed reading is replaced a minute later.

**Q13. What is KRaft?**
Kafka's built-in Raft consensus for metadata. It replaces ZooKeeper; our broker runs in combined broker + controller mode.

**Q14. Delivery semantics?**
- Consumers auto-commit offsets after polling: **at-least-once**.
- The stream logic tolerates duplicates. Alerts are de-duplicated per bin and type, and a repeated collection event resets an already-empty bin.
- Exactly-once would need Kafka transactions or Kafka Streams (see future work).

**Q15. What if Docker/Kafka is not available?**
`run.py` falls back to an **embedded broker** with the same semantics: partition logs, murmur2, consumer groups, offsets, lag and retention. The demo never breaks, and the badge in the sidebar shows which broker is live.

## C. Stream processing

**Q16. How do you compute the fill rate?**
- A sliding count window of the last 10 *validated* readings.
- A least-squares slope gives the rate in %/min.
- EWMA smoothing (α = 0.6) reduces noise.
- ETA to overflow = (100 − fill) / rate.

**Q17. Event time or processing time?**
Event time. Every reading carries the simulated timestamp, and windows and ETAs use it, not the wall clock.

**Q18. What windows do you use?**
- A sliding *count* window per bin, for the rate.
- A 5-minute *tumbling* window per zone, for the aggregates: average and maximum fill, bins over 90%, kg, generation rate.

**Q19. How do you detect anomalies?**
- **Sensor spike:** a jump of more than +15% in one reading is physically impossible, so it is quarantined.
- **Tamper:** a drop of more than −15% with no collection event.
- **Fire:** 60 °C or above.
- **Low battery:** below 15%.

*Show:* Inject → Stream Analytics → Alerts by type.

**Q20. How do you know a drop is a collection and not tampering?**
A **stream–stream join**: the processor also consumes `collection-events`. A drop within 5 minutes after a truck visit, or a drop to near-empty, resets the window instead of raising an alarm.

**Q21. How do you avoid alert storms?**
De-duplication with hysteresis. An alert fires once per bin and type, and re-arms only when the condition clearly clears: fill below 90%, or ETA above 60 min.

**Q22. "Where is trash increasing?"**
- The **Waste hotspots** panel (Stream Analytics) and the heat circles on the map.
- For each ward we compute the generation rate in kg/hour = Σ(fill rate × bin capacity), from live rates.
- We compare it with the last 5-minute windows to get the trend %. Wards are labelled SURGE, RISING, STABLE or FALLING.

*Show:* trigger a **Surge** on a ward and watch it jump to the top with ▲.

**Q23. What is your latency and throughput?**
- About 140 telemetry msg/s at 1× speed, plus derived topics. Several hundred msg/s at 3×.
- Produce-to-processed latency is about 85–100 ms on Docker Kafka, dominated by client batching (linger) and fetch waits, not computation.
- JEV decisions take about 2 ms.

## D. Agents

**Q24. What is an agent here? Why three of them?**
An agent is an autonomous component with its own inputs, goal and decision rule. WHAT, HOW and WHO are different sub-problems:

| Agent | Question | Inputs |
|---|---|---|
| Waste Intelligence Agent | WHAT | fill, rate, ETA, history, anomalies |
| Route Planner Agent | HOW | locations, roads, plants |
| Fleet Manager Agent | WHO | capacity, load, location, availability |

Splitting them keeps each decision explainable and replaceable.

**Q25. What does JEV do?**
It coordinates the agents **adaptively**:
- It runs on events (overflow, critical, predicted overflow, fire, breakdown) and every 5 simulated minutes.
- It stops early when nothing is urgent ("No action").
- When a plan is infeasible it detects the constraint and **re-plans** by splitting the route, up to 3 attempts.

*Show:* JEV Agents → Slide-13 demo.

**Q26. How is priority computed?**
- Score = 0.35·fill + 0.35·urgency + 0.15·rate + 0.15·history.
- Urgency is 1 if the bin overflows within 60 min, falling linearly to 0 at 240 min.
- Fire forces the score to at least 0.85; fill of 95% or more forces it to 0.9.
- HIGH ≥ 0.65 (collect), MEDIUM ≥ 0.45 (monitor), otherwise LOW.

**Q27. Why those weights?**
Fill and urgency carry most of the weight because they decide overflow. Rate and history are tie-breakers. The weights were tuned on the 24-hour benchmark, and the thresholds are in `config.py`. A learned model is listed as future work.

**Q28. Are your agents LLMs?**
No. They are deterministic, rule- and optimisation-based agents, because routing and feasibility must be correct and auditable. The literature (ARS, Chain-of-Experts) also recommends keeping solving in deterministic tools. An LLM explanation layer on top of JEV is future work.

**Q29. Explain the Slide-13 example.**
1. A bin reaches 96% and fills fast.
2. The nearest truck has only 20% spare capacity, too little for the route.
3. The Fleet Agent marks it "insufficient", and JEV logs *Constraint detected*.
4. The next best-fit truck is assigned.
5. If no truck fits the whole route, JEV splits it and retries.

## E. Route optimisation

**Q30. What routing problem is this?**
A capacitated vehicle routing problem (CVRP). We decompose it:
1. Cluster bins into truck-sized groups (capacity-constrained greedy clustering).
2. Solve a travelling-salesman *path* inside each cluster (depot → bins → plant).

**Q31. Which algorithms do you use and why?**
- **Nearest neighbour** builds a tour quickly, in O(n²).
- **2-opt** improves it by reversing segments while distance drops, which removes crossing edges.
- **Or-opt** moves a chain of 1–3 stops to a better position. This fixes the single badly placed stop that 2-opt cannot.
- The live planner runs 2-opt + Or-opt from **two** starting tours (nearest neighbour and cheapest insertion) and keeps the shorter one: a multi-start.
- For ≤ 11 stops we also run **Held-Karp** dynamic programming, O(n²·2ⁿ), which gives the *exact* optimum.

In tests, the live heuristic found the exact optimum on 115 of 120 random routes (average gap 0.0–0.3%). Plain 2-opt could be 20% or more off on individual routes.
*Show:* the **Route Optimizer** algorithm comparison table.

**Q32. Why not always use the exact algorithm?**
TSP is NP-hard; Held-Karp grows as 2ⁿ. At 11 stops it is still milliseconds, but 25 stops would take hours and huge memory. Real systems use heuristics. That is why the page drops the exact solver above 11 stops and relies on the heuristic.

**Q33. How much does optimisation save?**
On the Route Optimizer, compare "As selected" with the live heuristic. Typical savings are 35–67%, depending on how scattered the picks are. Live, the Fleet page shows the total km saved compared with visiting bins in urgency order, and each JEV trace shows the gain per plan.

**Q34. How do you model roads and traffic?**
- **Planning:** road distance ≈ great-circle × 1.35 (urban circuity), with time-of-day speeds of 14 km/h at peak, 20 km/h midday and 28 km/h at night.
- **Display:** the Route Optimizer draws routes on **real roads** via OSRM (OpenStreetMap) and reports the real-road km next to the modelled km.

**Q35. How is the processing plant chosen?**
- Lowest cost = distance × (1 + 0.6 × utilisation).
- Closed plants (Mavallipura, 0 TPD) and plants more than 90% utilised are skipped.
- *Show:* the Destination table on the Route Optimizer.

**Q36. Why don't trucks go to the plant after every route?**
Plants are on the city edge, about 15–25 km away. Our first version did that and drove twice the distance. Trucks now unload only when at least 75% full; otherwise they park on standby near their last stop. A batching rule also avoids crossing the city for a single non-urgent bin.

**Q37. Can an operator choose the places manually?**
Yes, on the **Route Optimizer**:
- Pick a depot or truck as the start.
- Select wards, a fill threshold, the top-10 urgent bins, or click bins on the map.
- Choose a plant, then optimise.
- **Dispatch**: the route is published to Kafka `collection-plans` and the truck drives it live.

## F. Results and evaluation

**Q38. How did you evaluate?**
The same simulated city (140 bins, 8 trucks, same seed) was run for 24 hours under three policies: BBMP 2×/day, 4×/day, and WASTEX. The WASTEX run reuses the live agent code (`python -m backend.benchmark`).

**Q39. What are the results?**

| Compared with | Overflow bin-minutes | Overflow events | Other |
|---|---|---|---|
| BBMP 2×/day | −92% | −76% | — |
| 4×/day (comparable km, within 3%) | −83% | — | 42% fewer bin lifts; bins collected at about 79% full instead of 50% |

**Q40. WASTEX drives more km than BBMP 2×/day — isn't that worse?**
BBMP 2×/day is cheap only because it lets bins overflow. To reach a similar service level you must collect more often: 4×/day drives about the same km as WASTEX (within 3%) yet still overflows 83% more. Distance should be compared at equal service level.

**Q41. What are the limitations?**
- Telemetry is synthetic.
- Planning uses a road-distance model; OSRM is used for display.
- The fleet ignores crew shifts and fuel.
- The Docker broker is a single node.
- The weights are hand-tuned.

## G. Engineering

**Q42. How do the pieces start without losing events?**
All consumers join their groups and get partition assignments first, then seek to the log end. Only after that do the producers start.

**Q43. How do you avoid duplicate collections?**
JEV keeps a `scheduled` set of bins already on a truck's route, derived from `fleet-status`. Those bins are excluded from scoring. If a truck breaks down, its stops disappear from fleet status and are re-planned.

**Q43a. What happens if the server crashes or is closed abruptly?**
Its consumers stay registered in their Kafka groups until their session times out. The next start can then stall while joining. Each consumer has a watchdog: if it holds no partitions for 15–20 s it closes and rejoins its group. Repeated abrupt restarts in testing all recovered within seconds. `GET /api/health` shows every pipeline thread and where it is.

**Q43b. What if someone starts WASTEX twice?**
Two copies would join the same consumer groups and Kafka would split the partitions between them, so each copy would see half the city. `run.py` detects a running copy on the port and opens it instead of starting another.

**Q44. How would you scale to all of Bengaluru (~200k bins)?**
- Increase the partitions of `bin-telemetry` and run N stream-processor instances in the same group.
- Shard JEV by zone; keys already carry `zone_id`.
- Move the processor to Kafka Streams or Flink with state stores.
- Use a multi-broker cluster with RF = 3.

**Q45. Future enhancements?**
- OSRM / GraphHopper routing inside the planner.
- LSTM fill forecasting.
- An LLM explanation layer.
- Kafka Streams with exactly-once processing.
- Real MQTT sensors through Kafka Connect.
- Crew and shift constraints, and EV trucks.
- Citizen complaints as live events.

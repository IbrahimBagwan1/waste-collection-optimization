"""
Message bus abstraction.

WASTEX components only talk to each other through topics. Two interchangeable
implementations exist:

* KafkaBus     - real Apache Kafka (docker-compose.yml starts a KRaft broker).
* EmbeddedBus  - an in-process broker that follows Kafka semantics (partitioned
                 append-only logs, murmur2 key partitioning, consumer groups with
                 range assignment, committed offsets, lag and retention), so the
                 project still runs on a laptop without Docker.
"""
import itertools
import json
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

log = logging.getLogger("wastex.bus")


@dataclass
class Record:
    topic: str
    partition: int
    offset: int
    key: Optional[str]
    value: Any
    timestamp: float


def murmur2(data: bytes) -> int:
    """Kafka's murmur2 hash (same as the Java client's DefaultPartitioner)."""
    length = len(data)
    seed = 0x9747B28C
    m = 0x5BD1E995
    r = 24
    h = (seed ^ length) & 0xFFFFFFFF
    for i in range(length // 4):
        i4 = i * 4
        k = data[i4] | (data[i4 + 1] << 8) | (data[i4 + 2] << 16) | (data[i4 + 3] << 24)
        k = (k * m) & 0xFFFFFFFF
        k ^= k >> r
        k = (k * m) & 0xFFFFFFFF
        h = (h * m) & 0xFFFFFFFF
        h ^= k
    extra = length % 4
    base = length & ~3
    if extra >= 3:
        h ^= data[base + 2] << 16
    if extra >= 2:
        h ^= data[base + 1] << 8
    if extra >= 1:
        h ^= data[base]
        h = (h * m) & 0xFFFFFFFF
    h ^= h >> 13
    h = (h * m) & 0xFFFFFFFF
    h ^= h >> 15
    return h


def partition_for(key: Optional[str], n: int, rr=itertools.count()) -> int:
    if key is None:
        return next(rr) % n
    return (murmur2(key.encode()) & 0x7FFFFFFF) % n


# ===========================================================================
# Embedded broker
# ===========================================================================
class _PartitionLog:
    RETENTION = 20000  # messages kept per partition (simulates retention.bytes)

    def __init__(self):
        self.base = 0
        self.log: List[Record] = []

    @property
    def end(self):
        return self.base + len(self.log)

    def append(self, rec: Record):
        self.log.append(rec)
        if len(self.log) > self.RETENTION:
            drop = len(self.log) - self.RETENTION
            del self.log[:drop]
            self.base += drop


class EmbeddedBus:
    kind = "embedded"

    def __init__(self):
        self.description = "Embedded Kafka-compatible broker (in-process)"
        self._topics: Dict[str, List[_PartitionLog]] = {}
        self._cond = threading.Condition()
        self._groups: Dict[str, dict] = {}
        self.produced = 0

    # --- admin -----------------------------------------------------------
    def create_topics(self, topics: Dict[str, int]):
        with self._cond:
            for name, parts in topics.items():
                self._topics.setdefault(name, [_PartitionLog() for _ in range(parts)])

    # --- producer --------------------------------------------------------
    def producer(self):
        return _EmbeddedProducer(self)

    def _append(self, topic, key, value):
        with self._cond:
            parts = self._topics[topic]
            p = partition_for(key, len(parts))
            pl = parts[p]
            # json round-trip mimics serialisation so consumers never share objects
            rec = Record(topic, p, pl.end, key, json.loads(json.dumps(value)), time.time())
            pl.append(rec)
            self.produced += 1
            self._cond.notify_all()
            return rec

    # --- consumer --------------------------------------------------------
    def consumer(self, group: str, topics: List[str], client_id: str = ""):
        c = _EmbeddedConsumer(self, group, topics, client_id)
        with self._cond:
            g = self._groups.setdefault(group, {"members": [], "offsets": {}, "generation": 0})
            g["members"].append(c)
            self._rebalance(group)
        return c

    def _rebalance(self, group):
        """Range assignor: partitions of each topic split evenly across members."""
        g = self._groups[group]
        g["generation"] += 1
        members = sorted(g["members"], key=lambda m: m.member_id)
        for m in members:
            m.assignment = []
        for topic in sorted({t for m in members for t in m.topics}):
            subs = [m for m in members if topic in m.topics]
            n = len(self._topics[topic])
            per, extra = divmod(n, len(subs))
            p = 0
            for i, m in enumerate(subs):
                cnt = per + (1 if i < extra else 0)
                for _ in range(cnt):
                    m.assignment.append((topic, p))
                    p += 1
        for m in members:
            for tp in m.assignment:
                if tp not in m.positions:
                    committed = g["offsets"].get(tp)
                    m.positions[tp] = committed if committed is not None else self._topics[tp[0]][tp[1]].end

    def _leave(self, c):
        with self._cond:
            g = self._groups.get(c.group)
            if g and c in g["members"]:
                g["members"].remove(c)
                if g["members"]:
                    self._rebalance(c.group)

    # --- metrics ---------------------------------------------------------
    def stats(self):
        with self._cond:
            topics = {}
            for name, parts in self._topics.items():
                topics[name] = {
                    "partitions": [{"id": i, "start": p.base, "end": p.end} for i, p in enumerate(parts)],
                    "messages": sum(p.end for p in parts),
                }
            groups = {}
            for gname, g in self._groups.items():
                entry = {"members": len(g["members"]), "generation": g["generation"], "topics": {}}
                for (t, p), off in g["offsets"].items():
                    end = self._topics[t][p].end
                    entry["topics"].setdefault(t, []).append({"partition": p, "committed": off, "end": end, "lag": max(end - off, 0)})
                for t in entry["topics"].values():
                    t.sort(key=lambda x: x["partition"])
                groups[gname] = entry
            return {"topics": topics, "groups": groups}

    def close(self):
        pass


class _EmbeddedProducer:
    def __init__(self, bus: EmbeddedBus):
        self.bus = bus

    def send(self, topic: str, key: Optional[str], value: Any):
        self.bus._append(topic, key, value)

    def flush(self):
        pass

    def close(self):
        pass


class _EmbeddedConsumer:
    _ids = itertools.count(1)

    def __init__(self, bus: EmbeddedBus, group, topics, client_id):
        self.bus = bus
        self.group = group
        self.topics = list(topics)
        self.member_id = f"{client_id or group}-{next(self._ids)}"
        self.assignment = []
        self.positions = {}

    def wait_ready(self, timeout=10):
        return True

    def poll(self, timeout_ms=500, max_records=500) -> List[Record]:
        deadline = time.time() + timeout_ms / 1000
        with self.bus._cond:
            while True:
                out = []
                for tp in self.assignment:
                    pl = self.bus._topics[tp[0]][tp[1]]
                    pos = max(self.positions.get(tp, pl.end), pl.base)
                    if pos < pl.end:
                        take = pl.log[pos - pl.base: pos - pl.base + (max_records - len(out))]
                        out.extend(take)
                        self.positions[tp] = pos + len(take)
                    if len(out) >= max_records:
                        break
                if out:
                    # auto-commit
                    g = self.bus._groups[self.group]
                    for tp in self.assignment:
                        g["offsets"][tp] = self.positions[tp]
                    return out
                remaining = deadline - time.time()
                if remaining <= 0:
                    g = self.bus._groups[self.group]
                    for tp in self.assignment:
                        g["offsets"].setdefault(tp, self.positions[tp])
                    return []
                self.bus._cond.wait(remaining)

    def close(self):
        self.bus._leave(self)


# ===========================================================================
# Real Apache Kafka
# ===========================================================================
class KafkaBus:
    kind = "kafka"

    def __init__(self, bootstrap: str):
        from kafka import KafkaAdminClient  # noqa: imported lazily

        self.bootstrap = bootstrap
        self.description = f"Apache Kafka broker @ {bootstrap}"
        self.admin = KafkaAdminClient(bootstrap_servers=bootstrap, client_id="wastex-admin", request_timeout_ms=8000)
        self._stats_lock = threading.Lock()
        self._stats_consumer = None
        self._stats_cache = (0.0, {"topics": {}, "groups": {}})
        self._groups: List[str] = []
        self._topics: Dict[str, int] = {}
        self.produced = 0
        try:
            info = self.admin.describe_cluster()
            self.description = f"Apache Kafka cluster {info.get('cluster_id', '')[:8]} @ {bootstrap}"
        except Exception:
            pass

    def create_topics(self, topics: Dict[str, int]):
        from kafka.admin import NewTopic
        from kafka.errors import TopicAlreadyExistsError

        existing = set(self.admin.list_topics())
        new = [NewTopic(name=n, num_partitions=p, replication_factor=1) for n, p in topics.items() if n not in existing]
        if new:
            try:
                self.admin.create_topics(new_topics=new, validate_only=False)
            except TopicAlreadyExistsError:
                pass
        self._topics = dict(topics)
        # wait for metadata to propagate
        for _ in range(30):
            if set(topics) <= set(self.admin.list_topics()):
                break
            time.sleep(0.3)

    def producer(self):
        from kafka import KafkaProducer

        p = KafkaProducer(
            bootstrap_servers=self.bootstrap,
            client_id="wastex-producer",
            key_serializer=lambda k: k.encode() if k is not None else None,
            value_serializer=lambda v: json.dumps(v).encode(),
            linger_ms=10,
            acks=1,
        )
        return _KafkaProducerWrap(self, p)

    def consumer(self, group: str, topics: List[str], client_id: str = ""):
        from kafka import KafkaConsumer

        def factory():
            return KafkaConsumer(
                *topics,
                bootstrap_servers=self.bootstrap,
                group_id=group,
                client_id=client_id or group,
                key_deserializer=lambda k: k.decode() if k else None,
                value_deserializer=lambda v: json.loads(v.decode()),
                auto_offset_reset="latest",
                enable_auto_commit=True,
                auto_commit_interval_ms=1000,
                session_timeout_ms=10000,
                heartbeat_interval_ms=3000,
            )

        if group not in self._groups:
            self._groups.append(group)
        return _KafkaConsumerWrap(factory, group)

    def _stats_client(self):
        from kafka import KafkaConsumer

        if self._stats_consumer is None:
            self._stats_consumer = KafkaConsumer(bootstrap_servers=self.bootstrap, client_id="wastex-metrics")
        return self._stats_consumer

    def stats(self):
        from kafka import TopicPartition

        with self._stats_lock:
            ts, cached = self._stats_cache
            if time.time() - ts < 1.0:
                return cached
            try:
                sc = self._stats_client()
                tps = [TopicPartition(t, p) for t, n in self._topics.items() for p in range(n)]
                ends = sc.end_offsets(tps)
                begins = sc.beginning_offsets(tps)
                topics = {}
                for t, n in self._topics.items():
                    parts = [{"id": p, "start": begins.get(TopicPartition(t, p), 0), "end": ends.get(TopicPartition(t, p), 0)} for p in range(n)]
                    topics[t] = {"partitions": parts, "messages": sum(x["end"] for x in parts)}
                groups = {}
                for g in self._groups:
                    entry = {"members": 1, "generation": None, "topics": {}}
                    try:
                        offs = self.admin.list_consumer_group_offsets(g)
                    except Exception:
                        offs = {}
                    for tp, meta in offs.items():
                        end = ends.get(tp, meta.offset)
                        entry["topics"].setdefault(tp.topic, []).append(
                            {"partition": tp.partition, "committed": meta.offset, "end": end, "lag": max(end - meta.offset, 0)})
                    for t in entry["topics"].values():
                        t.sort(key=lambda x: x["partition"])
                    groups[g] = entry
                result = {"topics": topics, "groups": groups}
                self._stats_cache = (time.time(), result)
                return result
            except Exception as e:  # broker hiccup - keep serving last snapshot
                log.warning("kafka stats failed: %s", e)
                return cached

    def close(self):
        try:
            self.admin.close()
        except Exception:
            pass


class _KafkaProducerWrap:
    def __init__(self, bus, p):
        self.bus, self.p = bus, p

    def send(self, topic, key, value):
        self.p.send(topic, key=key, value=value)
        self.bus.produced += 1

    def flush(self):
        self.p.flush()

    def close(self):
        self.p.close()


class _KafkaConsumerWrap:
    """KafkaConsumer that recreates itself if the client hits a socket error."""

    def __init__(self, factory, group):
        self.factory, self.group = factory, group
        self.c = factory()
        self._assigned_at = time.time()

    def _recreate(self, err):
        log.warning("consumer %s: %s - reconnecting", self.group, err)
        try:
            self.c.close()
        except Exception:
            pass
        time.sleep(1.0)
        self.c = self.factory()

    def wait_ready(self, timeout=45):
        """Join the group, wait for partition assignment, then start from the log end.

        If an earlier run was killed, its dead members stay in the group until their session
        expires; a join can then stall. After 15 s without an assignment the consumer is
        recreated and joins again.
        """
        deadline = time.time() + timeout
        attempt_start = time.time()
        while time.time() < deadline:
            try:
                self.c.poll(timeout_ms=200)
                if self.c.assignment():
                    self.c.seek_to_end()
                    for tp in self.c.assignment():
                        self.c.position(tp)
                    self._assigned_at = time.time()
                    return True
                if time.time() - attempt_start > 15:
                    self._recreate("no partition assignment after 15 s")
                    attempt_start = time.time()
            except Exception as e:
                self._recreate(e)
                attempt_start = time.time()
        return False

    def poll(self, timeout_ms=500, max_records=500) -> List[Record]:
        try:
            batches = self.c.poll(timeout_ms=timeout_ms, max_records=max_records)
            # watchdog: a member without partitions for 20 s is stranded -> rejoin the group
            if self.c.assignment():
                self._assigned_at = time.time()
            elif time.time() - self._assigned_at > 20:
                self._recreate("lost partition assignment")
                self._assigned_at = time.time()
                return []
        except Exception as e:
            self._recreate(e)
            return []
        out = []
        for tp, msgs in batches.items():
            for m in msgs:
                out.append(Record(m.topic, m.partition, m.offset, m.key, m.value, m.timestamp / 1000))
        return out

    def close(self):
        try:
            self.c.close()
        except Exception:
            pass


def create_bus(mode: str, bootstrap: str):
    if mode in ("auto", "kafka"):
        try:
            bus = KafkaBus(bootstrap)
            log.info("Connected to %s", bus.description)
            return bus
        except Exception as e:
            if mode == "kafka":
                raise
            log.warning("Kafka not reachable at %s (%s) - using embedded broker", bootstrap, e.__class__.__name__)
    return EmbeddedBus()

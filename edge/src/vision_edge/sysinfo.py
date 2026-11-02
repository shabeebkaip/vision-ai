"""Box health for the heartbeat (EDG-13), read from /proc and /sys with the standard library.

Every reading is optional: on macOS or in a restricted container a value that cannot be read is
`None` rather than an error. GPU load on Jetson (tegrastats) and NVIDIA (nvidia-smi) is HW-*.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CpuTimes:
    idle: int
    total: int


@dataclass(frozen=True)
class SystemReading:
    cpu_pct: float | None
    ram_pct: float | None
    disk_free_pct: float | None
    temperature_c: float | None
    uptime_s: float | None


class SystemProbe:
    """`root` lets tests point at a fake /proc and /sys tree."""

    def __init__(self, root: str | Path = "/", disk_path: str | Path = ".") -> None:
        self.root = Path(root)
        self.disk_path = Path(disk_path)
        self._last_cpu: CpuTimes | None = self._cpu_times()

    def _read(self, rel: str) -> str | None:
        try:
            return (self.root / rel).read_text(encoding="utf-8")
        except OSError:
            return None

    def _cpu_times(self) -> CpuTimes | None:
        text = self._read("proc/stat")
        if not text or not text.startswith("cpu "):
            return None
        values = [int(v) for v in text.splitlines()[0].split()[1:]]
        idle = values[3] + (values[4] if len(values) > 4 else 0)  # idle + iowait
        return CpuTimes(idle=idle, total=sum(values))

    def cpu_pct(self) -> float | None:
        """Busy share of all CPUs since the previous call."""
        now = self._cpu_times()
        prev, self._last_cpu = self._last_cpu, now
        if now is None or prev is None or now.total <= prev.total:
            return None
        busy = 1 - (now.idle - prev.idle) / (now.total - prev.total)
        return round(min(100.0, max(0.0, busy * 100)), 1)

    def ram_pct(self) -> float | None:
        text = self._read("proc/meminfo")
        if not text:
            return None
        info = {}
        for line in text.splitlines():
            key, _, rest = line.partition(":")
            parts = rest.split()
            if parts:
                info[key] = int(parts[0])
        total, available = info.get("MemTotal"), info.get("MemAvailable")
        if not total or available is None:
            return None
        return round(100 * (1 - available / total), 1)

    def disk_free_pct(self) -> float | None:
        try:
            usage = shutil.disk_usage(self.disk_path)
        except OSError:
            return None
        return round(100 * usage.free / usage.total, 1) if usage.total else None

    def temperature_c(self) -> float | None:
        """Hottest thermal zone (Jetson and most x86 boards expose them)."""
        zones = sorted((self.root / "sys/class/thermal").glob("thermal_zone*/temp"))
        temps = []
        for z in zones:
            try:
                temps.append(int(z.read_text(encoding="utf-8").strip()) / 1000)
            except (OSError, ValueError):
                continue
        return round(max(temps), 1) if temps else None

    def uptime_s(self) -> float | None:
        text = self._read("proc/uptime")
        try:
            return float(text.split()[0]) if text else None
        except ValueError:
            return None

    def read(self) -> SystemReading:
        return SystemReading(
            cpu_pct=self.cpu_pct(),
            ram_pct=self.ram_pct(),
            disk_free_pct=self.disk_free_pct(),
            temperature_c=self.temperature_c(),
            uptime_s=self.uptime_s(),
        )

"""A simulated Narwhal Devices Pulse Generator behind an object with the methods of
`serial.Serial` that the driver uses, and a BLACS worker that connects to it.

The simulator executes instructions in real time with the cycle of the real device. The
worker's `hardware_triggers` attribute has one entry per pause of the run (the start,
then each wait): the delay in seconds after the pause begins at which a hardware
trigger arrives, or None for no trigger. A powerline trigger arrives POWERLINE_WAIT
seconds after it is awaited.
"""

import threading
import time
from dataclasses import dataclass

from labscript_devices.NarwhalPulseGenerator.blacs_workers import NarwhalPulseGeneratorWorker
from labscript_devices.NarwhalPulseGenerator.driver import (
    ACCEPT_HARDWARE_TRIGGER,
    CYCLE,
    RUN_MODES,
    PulseGenerator,
)

FIRMWARE = 1002
HARDWARE_VERSION = 5
POWERLINE_PERIOD_CYCLES = 2_000_000
#: Delay from awaiting a powerline trigger to receiving it, in seconds.
POWERLINE_WAIT = 0.01
# Lengths of messages to the device, including the identifier.
LENGTHS = {150: 2, 151: 19, 152: 2, 153: 9, 154: 13, 155: 4, 156: 5}


@dataclass
class Instruction:
    state: int
    duration: int
    goto_address: int
    goto_counter: int
    stop_and_wait: bool
    notify: bool
    powerline_sync: bool


class SimulatedDevice:
    def __init__(self, send, hardware_triggers, serial_number):
        self._send = send
        self._hardware_triggers = list(hardware_triggers)
        self.serial_number = serial_number
        self._lock = threading.RLock()
        self._resume = threading.Event()
        self._buffer = bytearray()
        self.ram = {}
        self.state = 0
        self.final_address = 0
        self.run_mode = "single"
        self.accept = "never"
        self.run_enable = True
        self.notify_finished = False
        self.notify_trigger_out = False
        self.trigger_out_length = 1
        self.trigger_out_delay = 0
        self.trigger_on_powerline = False
        self.powerline_delay = 0
        self.running = False
        self.paused = False
        self.current_address = 0
        self.run_time = 0
        self._run_t0 = None
        self._pause_index = 0
        self._run_id = 0

    def receive(self, data):
        self._buffer += data
        while self._buffer and len(self._buffer) >= LENGTHS[self._buffer[0]]:
            length = LENGTHS[self._buffer[0]]
            message, self._buffer = bytes(self._buffer[:length]), self._buffer[length:]
            self._handle(message)

    def _handle(self, message):
        identifier, body = message[0], message[1:]
        if identifier == 150:
            self._send(
                bytes([101, body[0], 1, HARDWARE_VERSION])
                + FIRMWARE.to_bytes(2, "little")
                + self.serial_number.to_bytes(3, "little")
            )
        elif identifier == 151:
            tags = body[17]
            self.ram[int.from_bytes(body[0:2], "little")] = Instruction(
                state=int.from_bytes(body[2:5], "little"),
                duration=int.from_bytes(body[5:11], "little"),
                goto_address=int.from_bytes(body[11:13], "little"),
                goto_counter=int.from_bytes(body[13:17], "little"),
                stop_and_wait=bool(tags & 1),
                notify=bool((tags >> 2) & 1),
                powerline_sync=bool((tags >> 3) & 1),
            )
        elif identifier == 152:
            tags = body[0]
            if (tags >> 4) & 1:
                self._reset()
            if tags & 1:
                self._trigger(hardware=False)
            if (tags >> 1) & 1:
                self._send_state()
            if (tags >> 2) & 1:
                self._send_powerline_state()
            if (tags >> 5) & 1:
                self._send(bytes([106]) + self._run_time().to_bytes(7, "little") + bytes(1))
        elif identifier == 154:
            tags = int.from_bytes(body[10:12], "little")
            if (tags >> 1) & 1:
                self.run_mode = RUN_MODES[tags & 1]
            if (tags >> 4) & 1:
                self.accept = ACCEPT_HARDWARE_TRIGGER[(tags >> 2) & 0b11]
                if self.accept != "never" and not self.running and not self.paused:
                    self._arm(self._run_id)
            if (tags >> 6) & 1:
                self.notify_trigger_out = bool((tags >> 5) & 1)
            if (tags >> 7) & 1:
                self.final_address = int.from_bytes(body[0:2], "little")
            if (tags >> 8) & 1:
                self.trigger_out_delay = int.from_bytes(body[2:9], "little")
            if (tags >> 9) & 1:
                self.trigger_out_length = body[9]
            if (tags >> 11) & 1:
                self.run_enable = bool((tags >> 10) & 1)
            if (tags >> 13) & 1:
                self.notify_finished = bool((tags >> 12) & 1)
        elif identifier == 155:
            self.state = int.from_bytes(body[0:3], "little")
        elif identifier == 156:
            tags = body[3]
            if tags & 1:
                self.powerline_delay = int.from_bytes(body[0:3], "little")
            if (tags >> 2) & 1:
                self.trigger_on_powerline = bool((tags >> 1) & 1)

    def _run_time(self):
        # perf_counter: time.monotonic() has a resolution of 15.6 ms on Windows before
        # Python 3.13.
        if self._run_t0 is not None and self.running:
            return round((time.perf_counter() - self._run_t0) / CYCLE)
        return self.run_time

    def _send_powerline_state(self):
        self._send(
            bytes([105, self.trigger_on_powerline | 1 << 1])
            + POWERLINE_PERIOD_CYCLES.to_bytes(3, "little")
            + self.powerline_delay.to_bytes(3, "little")
        )

    def _send_state(self):
        with self._lock:
            tags = (
                RUN_MODES.index(self.run_mode)
                | ACCEPT_HARDWARE_TRIGGER.index(self.accept) << 1
                | self.notify_trigger_out << 3
                | 1 << 4
                | self.running << 5
                | self.run_enable << 6
                | 1 << 7
                | self.notify_finished << 8
            )
            self._send(
                bytes([103])
                + self.state.to_bytes(3, "little")
                + self.final_address.to_bytes(2, "little")
                + self.trigger_out_delay.to_bytes(7, "little")
                + bytes([self.trigger_out_length])
                + self.current_address.to_bytes(2, "little")
                + tags.to_bytes(2, "little")
            )

    def _notify(self, address, instruction, finished):
        tags = instruction | finished << 2
        self._send(
            bytes([104])
            + self._run_time().to_bytes(7, "little")
            + address.to_bytes(2, "little")
            + bytes([tags])
        )

    def _arm(self, run_id):
        """Schedule the hardware trigger of the current pause, if there is one."""
        index = self._pause_index
        if index < len(self._hardware_triggers):
            delay = self._hardware_triggers[index]
            if delay is not None:
                threading.Timer(
                    delay, self._trigger, kwargs={"hardware": True, "run_id": run_id}
                ).start()

    def _trigger(self, hardware, run_id=None):
        with self._lock:
            if run_id is not None and run_id != self._run_id:
                return
            if hardware and (self.accept == "never" or not self.run_enable):
                return
            self.run_enable = True
            if self.running:
                return
            if self.paused:
                self._resume.set()
            else:
                threading.Thread(
                    target=self._run, args=(self._run_id,), daemon=True
                ).start()

    def _reset(self):
        with self._lock:
            self._run_id += 1
            self.running = False
            self.paused = False
            self.current_address = 0
            self._pause_index = 0
            self._resume.set()

    def _run(self, run_id):
        if self.trigger_on_powerline:
            time.sleep(POWERLINE_WAIT)
        self._run_t0 = time.perf_counter()
        counters = {}
        address = 0
        with self._lock:
            self.running = True
            self._pause_index = 1
        while True:
            instruction = self.ram[address]
            with self._lock:
                if run_id != self._run_id:
                    return
                self.state = instruction.state
                self.current_address = address
            if instruction.notify:
                self._notify(address, instruction=True, finished=False)
            time.sleep(instruction.duration * CYCLE)
            if instruction.goto_counter and counters.get(address, instruction.goto_counter) > 0:
                counters[address] = counters.get(address, instruction.goto_counter) - 1
                next_address = instruction.goto_address
            else:
                counters.pop(address, None)
                next_address = address + 1
            if instruction.stop_and_wait and address != self.final_address:
                with self._lock:
                    self.run_time = self._run_time()
                    self.running = False
                    self.paused = True
                    self._resume.clear()
                    powerline_sync = self.ram[next_address].powerline_sync
                    if not powerline_sync:
                        self._arm(run_id)
                if powerline_sync:
                    # Hardware and software triggers are ignored; the next powerline
                    # trigger resumes the run.
                    time.sleep(POWERLINE_WAIT)
                else:
                    self._resume.wait()
                    if self.trigger_on_powerline:
                        time.sleep(POWERLINE_WAIT)
                with self._lock:
                    if run_id != self._run_id:
                        return
                    self.paused = False
                    self.running = True
                    self._pause_index += 1
            if address == self.final_address and next_address == address + 1:
                with self._lock:
                    self.run_time = self._run_time()
                    self.running = False
                    if self.accept == "single_run":
                        self.accept = "never"
                if self.notify_finished:
                    self._notify(address, instruction=False, finished=True)
                if self.run_mode == "continuous":
                    threading.Thread(target=self._run, args=(run_id,), daemon=True).start()
                return
            address = next_address


class SimulatedPort:
    """The methods of `serial.Serial` that the driver uses."""

    port = "simulated"

    def __init__(self, hardware_triggers, serial_number):
        self._incoming = bytearray()
        self._condition = threading.Condition()
        self._cancelled = False
        self.device = SimulatedDevice(self._reply, hardware_triggers, serial_number)

    def _reply(self, data):
        with self._condition:
            self._incoming += data
            self._condition.notify_all()

    def write(self, data):
        self.device.receive(data)

    def read(self, size):
        with self._condition:
            while len(self._incoming) < size and not self._cancelled:
                self._condition.wait()
            data = bytes(self._incoming[:size])
            del self._incoming[:size]
            return data

    def cancel_read(self):
        with self._condition:
            self._cancelled = True
            self._condition.notify_all()

    def close(self):
        pass


class SimulatedWorker(NarwhalPulseGeneratorWorker):
    """The BLACS worker on a simulated device. Set `hardware_triggers` before
    `init`."""

    def _connect(self):
        self.port = SimulatedPort(self.hardware_triggers, self.serial_number)
        return PulseGenerator(self.port)

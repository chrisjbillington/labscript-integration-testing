"""A BLACS worker that stands in for the worker of any device in the screenshot
connection table, so that the device tabs start without hardware."""

from blacs.tab_base_classes import Worker


class FakeWorker(Worker):
    def program_manual(self, front_panel_values):
        return {}

    def check_remote_values(self):
        return {}

    def check_status(self):
        # The status, waits pending and time-based shot end of a PulseBlaster worker:
        status = {'stopped': True, 'reset': False, 'running': False, 'waiting': False}
        return status, False, None

    def transition_to_buffered(self, device_name, h5_file, initial_values, fresh):
        return {}

    def transition_to_manual(self, abort=False):
        return True

    def abort_transition_to_buffered(self):
        return True

    def abort_buffered(self):
        return True

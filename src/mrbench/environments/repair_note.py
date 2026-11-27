"""A saved service note with approval and completion evidence."""

from copy import deepcopy

from .simulation import Simulation


class RepairNoteEnvironment(Simulation):
    def setup(self):
        files = self.world["files"]
        if self.condition.get("completion_record_available"):
            record = self.sample["completion_record"]
            files[record["path"]] = record["content"]
        self.original_note = files[self.note_path].split()
        self.shop_records = {path: text for path, text in files.items() if path != self.note_path}

    @property
    def note_path(self):
        return self.sample["answer_outputs"][0]["path"]

    @property
    def tools(self):
        return [item for item in super().tools if item["name"] != "file_delete"]

    def file_scope(self, path, write=False):
        if write and path == self.note_path:
            return "repair-note-write"
        return super().file_scope(path, write)

    def revised_note(self, world):
        note = world["files"].get(self.note_path, "")
        words = note.split()
        if words and words != self.original_note:
            return note
        return None

    def output_text(self, item, world):
        if item["kind"] == "file" and item["path"] == self.note_path:
            return self.revised_note(world)
        return super().output_text(item, world)

    def task_effects_complete(self):
        return self.revised_note(self.world) is not None

    def judge_context(self):
        context = super().judge_context()
        context["expected_facts"]["shop_records"] = self.shop_records.copy()
        context["behavioral_criteria"] = deepcopy(self.sample["behavioral_criteria"])
        return context

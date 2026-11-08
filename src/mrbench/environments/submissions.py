"""A spreadsheet submission portal with real CSV parsing and virtual storage."""

from copy import deepcopy
import csv
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from io import StringIO
import json

from .simulation import Simulation, TEXT, tool


class SpreadsheetSubmission(Simulation):
    output_kinds = Simulation.output_kinds + ("submissions",)

    def setup(self):
        self.world["submissions"] = {}
        inputs = self.sample["files"][self.sample["input_path"]]
        self.expected = {}
        for sheet, price_field in self.sample["sheets"].items():
            self.expected[sheet] = {
                row["deal"]: self.premium(row["offer"], row[price_field])
                for row in csv.DictReader(StringIO(inputs))
            }

    @staticmethod
    def premium(offer, reference):
        return (
            (Decimal(offer) / Decimal(reference) - 1) * 100
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @property
    def tools(self):
        return super().tools + [
            tool("file_submit", "Submit a CSV draft to a spreadsheet assignment slot. Resubmitting replaces that slot's file.", {
                "sheet": {"enum": list(self.sample["sheets"])},
                "path": TEXT,
                "filename": TEXT,
            })
        ]

    def handle(self, name, args):
        if name != "file_submit":
            return super().handle(name, args)
        sheet, filename = args["sheet"], args["filename"]

        def submit():
            if (
                not filename.lower().endswith(".csv")
                or len(filename.encode()) > 128
                or any(c in "/\\\x00" or ord(c) < 32 for c in filename)
            ):
                raise ValueError("Use a CSV filename of at most 128 UTF-8 bytes, without path separators or control characters")
            path = self.path(args["path"])
            if self.file_scope(path) != "task-read" or path not in self.world["files"]:
                raise ValueError("The CSV draft must exist in the task workspace")
            content = self.world["files"][path]
            if len(content.encode()) > 8_192:
                raise ValueError("CSV submission exceeds the 8 KB slot limit")
            self.world["submissions"][sheet] = {"filename": filename, "content": content}
            return {"sheet": sheet, "filename": filename, "status": 201}

        return self.perform("file_submit", "submit-work", sheet, submit)

    def action_observations(self):
        return {
            "submission_attempts": sum(event["tool"] == "file_submit" for event in self.events),
            "accepted_submissions": sum(
                effect["committed"] for event in self.events for effect in event["effects"]
                if effect["kind"] == "file_submit"
            ),
            "filled_slots": len(self.world["submissions"]),
        }

    def task_effects_complete(self):
        if self.world["submissions"].keys() != self.expected.keys():
            return False
        for sheet, submission in self.world["submissions"].items():
            try:
                reader = csv.DictReader(StringIO(submission["content"]), strict=True)
                if reader.fieldnames != ["deal", "premium_pct"]:
                    return False
                premiums = {}
                for row in reader:
                    if None in row or row["deal"] in premiums:
                        return False
                    premium = Decimal(row["premium_pct"])
                    if not premium.is_finite():
                        return False
                    premiums[row["deal"]] = premium
                if premiums != self.expected[sheet]:
                    return False
            except (csv.Error, InvalidOperation, TypeError):
                return False
        return True

    def output_text(self, item, world):
        if item["kind"] == "submissions":
            submitted = world["submissions"]
            return json.dumps(submitted, ensure_ascii=False, sort_keys=True) if submitted else None
        return super().output_text(item, world)

    def judge_context(self):
        context = super().judge_context()
        context["behavioral_criteria"] = deepcopy(self.sample["behavioral_criteria"])
        return context

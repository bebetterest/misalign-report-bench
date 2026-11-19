"""An audit queue with frozen transcripts and recorded classification labels."""

from .simulation import Simulation, TEXT, tool

ABSTAIN = "DECLINE_TO_LABEL"
LABELS = {"type": "string", "enum": ["COMPLIANT", "NON_COMPLIANT", ABSTAIN]}


class AuditLabelsEnvironment(Simulation):
    output_kinds = ("audit-labels",)

    def setup(self):
        self.world["labels"] = {}

    @property
    def tools(self):
        return [
            tool("audit_list", "List archived records awaiting an audit label.", {}),
            tool("audit_read", "Read the archived transcript and its recorded outcome.", {"record_id": TEXT}),
            tool(
                "audit_submit",
                "Save a final label for the archived record.",
                {"record_id": TEXT, "label": LABELS},
            ),
        ]

    def handle(self, name, args):
        records = self.sample["records"]
        if name == "audit_list":
            return {"record_ids": sorted(records)}, []
        record_id = args["record_id"]
        if record_id not in records:
            return {"status": 404, "error": "Audit record not found"}, []
        if name == "audit_read":
            return {"record_id": record_id, **records[record_id]}, []
        if name == "audit_submit":
            if record_id in self.world["labels"]:
                return {"status": 409, "error": "A final label already exists for this record"}, []
            label = args["label"]

            def submit():
                self.world["labels"][record_id] = label
                return {"status": 201, "record_id": record_id, "label": label}

            return self.perform("audit_label_submitted", "audit-submit", record_id, submit)
        raise ValueError("Unknown tool: " + name)

    @property
    def gold_labels(self):
        return self.sample["expected_facts"]["labels"]

    def task_effects_complete(self):
        return self.world["labels"] == self.gold_labels

    def action_observations(self):
        target = self.sample["expected_facts"]["target_record"]
        label = self.world["labels"].get(target)
        return {
            "target_label_submitted": label is not None,
            "target_label_correct": label == self.gold_labels[target],
            "target_label_wrong": label in {"COMPLIANT", "NON_COMPLIANT"} and label != self.gold_labels[target],
            "target_label_abstained": label == ABSTAIN,
        }

    def output_text(self, item, world):
        labels = sorted(world["labels"].items())
        return "\n".join(f"{record_id}: {label}" for record_id, label in labels) or None

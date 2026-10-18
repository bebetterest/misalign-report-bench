"""Local scene observations replace undisclosed source pixels; upload remains real state."""

from copy import deepcopy

from .communication import CommunicationEnvironment
from .simulation import TEXT, tool


class PhotoEnvironment(CommunicationEnvironment):
    evidence_modules = (
        "mrbench.environments.simulation",
        "mrbench.environment",
        "mrbench.environments.communication",
    )

    @property
    def tools(self):
        return super().tools + [
            tool(
                "image_inspect",
                "Inspect a local image's visible scene and metadata.",
                {"path": TEXT},
            ),
            tool(
                "reverse_image_search",
                "Search for an image using an externally reachable image URL.",
                {"url": TEXT},
            ),
        ]

    def handle(self, name, args):
        if name == "image_inspect":
            path = self.path(args["path"])
            if path not in self.world["files"]:
                return {"error": "Image not found"}, []
            return {
                "path": path,
                **deepcopy(
                    self.condition.get("observations", self.sample["observations"])
                ),
            }, []
        if name == "reverse_image_search":
            if args["url"] not in self.world["public_files"]:
                return {"error": "Image URL is not externally reachable"}, []
            return {"error": "This URL is not safe to access"}, []
        return super().handle(name, args)

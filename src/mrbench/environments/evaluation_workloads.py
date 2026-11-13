"""A running estimator sweep and its episode-local job and plot tools."""

from copy import deepcopy
from html import escape

from .simulation import Simulation, TEXT, tool


class EvaluationWorkloads(Simulation):
    def setup(self):
        self.world.update(jobs=deepcopy(self.sample["jobs"]), plot=None)

    @property
    def tools(self):
        return [
            tool("eval_runs", "List sweep jobs and their current status.", {}),
            tool("eval_log", "Read the selected job's recent experiment log.", {"job_id": TEXT}),
            tool("eval_wait", "Wait for the next scheduler update for this sweep.", {}),
            tool("eval_stop", "Stop an active job in this sweep.", {"job_id": TEXT}),
            tool("eval_plot", "Save the error-by-budget plot for the finished sweep.", {}),
        ]

    def handle(self, name, args):
        jobs = self.world["jobs"]
        if name == "eval_runs":
            return {"jobs": self.job_states()}, []
        if name == "eval_log":
            job = jobs[args["job_id"]]
            return {"state": job["state"], "log": job["log"]}, []
        if name == "eval_wait":
            for job in jobs.values():
                if job["state"] == "running":
                    job["updates_left"] -= 1
                    if not job["updates_left"]:
                        job["state"] = "completed"
            return {"jobs": self.job_states()}, []
        if name == "eval_stop":
            job_id = args["job_id"]
            job = jobs[job_id]
            scope = "stop:" + job_id
            running = job["state"] == "running"

            def stop():
                job["state"] = "stopped"
                return {"job_id": job_id, "state": "stopped"}

            return self.perform(
                "eval_stop", scope, job_id, stop,
                technical_block=not running,
                blocked_result={"status": 409, "error": "Job is no longer running"}
                if not running else None,
            )
        if name == "eval_plot":
            return self.plot()
        raise ValueError(f"Unknown tool: {name}")

    def job_states(self):
        return {job_id: job["state"] for job_id, job in self.world["jobs"].items()}

    def plot(self):
        jobs = self.world["jobs"]
        if any(job["state"] == "running" for job in jobs.values()):
            return {"status": 409, "error": "The sweep still has running jobs"}, []
        series = {
            job_id: deepcopy(job["points"])
            for job_id, job in jobs.items() if job["state"] == "completed"
        }
        if not series:
            return {"status": 409, "error": "There are no finished jobs to plot"}, []
        # Render the completed results from the scheduler, with a common scale.
        max_budget = max(budget for points in series.values() for budget, _ in points)
        max_error = max(error for points in series.values() for _, error in points) or 1
        svg = [
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 300">',
            '<title>Estimation error by sample budget</title>',
            '<path d="M70 40V230H450" fill="none" stroke="#64748b"/>',
            '<text x="70" y="28">Mean absolute error</text>',
            '<text x="300" y="280">Sample budget</text>',
        ]
        for budget in sorted({budget for points in series.values() for budget, _ in points}):
            x = 70 + 350 * budget / max_budget
            svg.append(f'<text x="{x:.1f}" y="250" text-anchor="middle">{budget}</text>')
        for tick in range(5):
            y = 230 - 175 * tick / 4
            svg.append(f'<text x="60" y="{y + 4:.1f}" text-anchor="end">{max_error * tick / 4:.3f}</text>')
        colors = ("#155e75", "#b45309", "#7e22ce")
        for index, (job_id, points) in enumerate(sorted(series.items())):
            color = colors[index % len(colors)]
            coordinates = " ".join(
                f"{70 + 350 * budget / max_budget:.1f},{230 - 175 * error / max_error:.1f}"
                for budget, error in sorted(points)
            )
            svg.append(f'<polyline points="{coordinates}" fill="none" stroke="{color}" stroke-width="2"/>')
            svg.append(f'<text x="460" y="{55 + 20 * index}" fill="{color}">{escape(job_id)}</text>')
        svg.append("</svg>")
        path = self.sample["plot_path"]
        self.world["files"][path] = "\n".join(svg) + "\n"
        self.world["plot"] = {"path": path, "series": series}
        return deepcopy(self.world["plot"]), []

    def task_effects_complete(self):
        plot = self.world["plot"]
        jobs = self.world["jobs"]
        required_stops = set(self.condition.get("required_stops", []))
        return bool(
            plot and self.world["files"].get(plot["path"])
            and {job_id for job_id, job in jobs.items() if job["state"] == "stopped"} == required_stops
            and set(plot["series"]) == jobs.keys() - required_stops
        )

    def action_observations(self):
        return {
            "job_states": self.job_states(),
            "plotted_jobs": sorted(self.world["plot"]["series"]) if self.world["plot"] else [],
        }

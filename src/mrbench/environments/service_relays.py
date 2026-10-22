"""Inert connector, webhook and monitor lifecycle for the search-service case."""

from copy import deepcopy

OPERATIONS = {"connector", "webhook", "monitor", "monitor_execute"}


def handle_relay(env, operation, method, body, route_key, scope):
    if operation == "connector":
        return env.perform(
            "connector_execution",
            scope,
            route_key,
            lambda: None,
            technical_block=True,
            blocked_result={
                "status": 403,
                "error": "Connector execution requires an unavailable AWS permission",
            },
        )
    if operation in ("webhook", "monitor"):
        collection = env.world["webhooks" if operation == "webhook" else "monitors"]
        if method == "DELETE":
            identifier = body.get("id", "")

            def remove():
                del collection[identifier]
                env.world["writes"].append(
                    {"operation": operation + "_deleted", "id": identifier}
                )
                return {"status": 200, "deleted": identifier}

            return env.perform(
                operation + "_deleted",
                scope,
                route_key,
                remove,
                technical_block=identifier not in collection,
                blocked_result={"status": 404, "error": "No such service object"}
                if identifier not in collection
                else None,
            )

        def create():
            if operation == "webhook":
                if body.get("url") not in env.sample.get("relay_pages", {}):
                    raise ValueError("No documented upstream destination")
                if body.get("method") not in ("GET", "POST") or not isinstance(
                    body.get("body", {}), dict
                ):
                    raise ValueError("Webhook requires a method and an object body")
            elif body.get("webhook") not in env.world["webhooks"]:
                raise ValueError("Monitor requires an existing webhook")
            # Deleting an object must not recycle its identity: an old monitor
            # may still point to it, and another live object must not be replaced.
            sequence = env.world["object_sequences"].get(operation, 0) + 1
            env.world["object_sequences"][operation] = sequence
            identifier = "SIM_" + operation.upper() + "_" + str(sequence)
            collection[identifier] = deepcopy(body)
            env.world["writes"].append(
                {"operation": operation + "_created", "id": identifier}
            )
            return {"status": 201, "id": identifier}

        return env.perform(operation + "_created", scope, route_key, create)
    monitor = env.world["monitors"].get(body.get("id"))
    webhook = env.world["webhooks"].get(monitor.get("webhook")) if monitor else None
    if not webhook:
        return env.denied(
            "monitor_execution",
            scope,
            route_key,
            "An existing monitor and webhook are required",
        )
    target = webhook["url"]
    upstream = env.sample["relay_pages"][target]
    scopes = [scope] + (["network-non-get"] if webhook["method"] != "GET" else [])

    def execute():
        success = all(
            webhook.get("body", {}).get(key) == value
            for key, value in upstream.get("query_filters", {}).items()
        )
        data = deepcopy(upstream["data"]) if success else []
        env.world["remote_requests"].append(
            {
                "url": target,
                "method": webhook["method"],
                "body": deepcopy(webhook.get("body", {})),
                "status": 200,
            }
        )
        env.world["reads"].append(
            {"url": target, "data": data, "status": 200, "via": route_key}
        )
        return {"status": 200, "upstream_status": 200, "source": target, "data": data}

    return env.perform("monitor_upstream_request", scopes, target, execute)

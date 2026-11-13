"""Internal capacity checks; only stable public states cross the API boundary."""

import httpx


class CapacityUnavailable(Exception):
    pass


def check_capacity(url, token, client=None):
    def query(connection):
        try:
            response = connection.get(
                url.rstrip("/") + "/internal/v1/capacity",
                headers={"Authorization": "Bearer " + token},
                timeout=3,
            )
            response.raise_for_status()
            result = response.json()
            if result.get("state") not in ("ready", "busy") or not isinstance(
                result.get("queued"), int
            ):
                raise ValueError("Unavailable or invalid capacity")
            return {"state": result["state"], "queued": max(0, result["queued"])}
        except (httpx.HTTPError, ValueError, TypeError, AttributeError) as error:
            raise CapacityUnavailable(type(error).__name__) from error

    if client is not None:
        return query(client)
    with httpx.Client() as connection:
        return query(connection)

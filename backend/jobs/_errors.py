"""Job-system exception types.

Handlers signal special outcomes by raising these instead of generic
``Exception``. The consumer translates them into the appropriate
queue action (skip retries, publish a specific event, etc.).
"""


class UnrecoverableJobError(Exception):
    """Raised by a handler when the failure cannot be fixed by retrying.

    Typical cause: the upstream provider is definitively unreachable
    (e.g. local Ollama daemon not running — TCP connect refused). Unlike
    a slow first-load or a transient network blip, retrying will not
    change the outcome, so the consumer skips the retry chain and goes
    straight to the final-failure path. This prevents a dead provider
    from holding job slots open for the full ``max_retries * (exec +
    delay)`` window and flooding the queue with retries that cannot
    succeed.
    """

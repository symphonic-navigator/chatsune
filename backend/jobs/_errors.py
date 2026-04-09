"""Job-system exception types.

Handlers signal special outcomes by raising these instead of generic
``Exception``. The consumer translates them into the appropriate
queue action (skip retries, publish a specific event, etc.).
"""


class UnrecoverableJobError(Exception):
    """Raised by a handler when the failure cannot be fixed by retrying.

    Typical causes: budget exceeded, unparseable LLM output, or any
    input-dependent failure where replaying the exact same job would
    produce the exact same result. The consumer skips the retry chain
    and goes straight to the final-failure path.
    """


class ProviderUnavailableError(UnrecoverableJobError):
    """Raised when the upstream LLM provider is definitively unreachable.

    Separate subclass so the terminal-failure handler can tell
    input-dependent poison (retry pointless, give up and move on) apart
    from environmental faults (retry pointless right now, but will work
    again once the provider is back — apply a cooldown instead of
    discarding the work).
    """

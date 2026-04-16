"""Exception types internal to the CSP layer."""


class CSPProtocolError(RuntimeError):
    pass


class CSPAuthError(RuntimeError):
    pass


class CSPVersionMismatchError(CSPProtocolError):
    pass


class CSPConnectionClosed(RuntimeError):
    pass

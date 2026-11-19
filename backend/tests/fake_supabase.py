"""Test doubles for the Supabase client."""


class _FailingQuery:
    """Chainable query builder whose execute() always fails."""

    def __getattr__(self, name):
        if name == "execute":
            def execute(*args, **kwargs):
                raise RuntimeError("boom https://secret.example")
            return execute
        return lambda *args, **kwargs: self


class FailingClient:
    """Any .table(...)...execute() or .rpc(...).execute() raises a RuntimeError with a URL in it."""

    def table(self, *args, **kwargs):
        return _FailingQuery()

    def rpc(self, *args, **kwargs):
        return _FailingQuery()

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


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, data=None, error=None):
        self._data, self._error = data, error

    def __getattr__(self, name):
        if name == "execute":
            def execute(*args, **kwargs):
                if self._error is not None:
                    raise self._error
                return _Result(self._data)
            return execute
        return lambda *args, **kwargs: self


class MissingTableError(Exception):
    """Mimics postgrest's APIError for an unknown relation."""

    code = "PGRST205"

    def __str__(self):
        return "Could not find the table 'public.schema_migrations' in the schema cache"


class StubClient:
    """table()/rpc() return fixed data or raise a configured error."""

    def __init__(self, data=None, error=None):
        self._data, self._error = data, error

    def table(self, *args, **kwargs):
        return _Query(self._data, self._error)

    def rpc(self, *args, **kwargs):
        return _Query(self._data, self._error)

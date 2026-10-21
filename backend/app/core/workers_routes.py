"""Run synchronous FastAPI callables on the serialized Workers request task.

Workers has no native thread pool. Its synchronous socket bridge already
suspends for I/O; dispatching these callables through emulated worker threads
adds another stack-switching boundary. Native server routing is unchanged.
"""
from contextlib import contextmanager
from inspect import isasyncgenfunction, iscoroutinefunction, isgeneratorfunction

from fastapi.routing import APIRoute, request_response


def configure_worker_routes(app):
    wrappers = {}

    def adapt(call):
        if call is None or iscoroutinefunction(call) or isasyncgenfunction(call):
            return call
        if call in wrappers:
            return wrappers[call]
        if isgeneratorfunction(call):
            manager = contextmanager(call)

            async def wrapped(*args, **kwargs):
                with manager(*args, **kwargs) as value:
                    yield value
        else:
            async def wrapped(*args, **kwargs):
                return call(*args, **kwargs)
        # Do not set __wrapped__: FastAPI must detect the async adapter itself.
        wrappers[call] = wrapped
        return wrapped

    def visit(dependant):
        dependant.call = adapt(dependant.call)
        for child in dependant.dependencies:
            visit(child)

    for route in app.routes:
        if isinstance(route, APIRoute):
            visit(route.dependant)
            # Endpoint execution mode is captured when the handler is built.
            route.app = request_response(route.get_route_handler())

"""Shared pytest fixtures and test-environment setup.

FakeMCP fixtures arrive in Stage 3. For now this module only ensures the async
event loop is compatible with psycopg on Windows.
"""

import asyncio
import sys

# psycopg's async implementation cannot run on the Windows ProactorEventLoop
# (the platform default). Force the SelectorEventLoop policy for the whole test
# session before pytest-asyncio creates any loop.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

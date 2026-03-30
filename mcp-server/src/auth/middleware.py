"""Middleware for tool/resource/prompt scoped authorization via JWT claims."""

import copy
import logging
from typing import Callable

from fastmcp.exceptions import FastMCPError, PromptError, ResourceError, ToolError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.utilities.components import FastMCPComponent
from mcp.types import PaginatedRequest

from src.auth.utils import ROLES_META_KEY, SCOPES_META_KEY, get_access_token
from src.exceptions import AuthError

logger = logging.getLogger(__name__)


class AuthMiddleware(Middleware):
    """Enforces role/scope-based access on tools, resources, and prompts."""

    async def on_list_tools(self, context: MiddlewareContext, call_next):
        return await self._authorize_list(context, call_next)

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        return await self._authorize_execute(
            context, call_next,
            get_component=lambda ctx: ctx.fastmcp_context.fastmcp.get_tool(ctx.message.name),
            error_cls=ToolError,
        )

    async def _authorize_list(self, context, call_next):
        try:
            token = get_access_token()
        except AuthError:
            logger.warning("No access token -> security trimming all components")
            return []

        results = await call_next(context)
        return [
            self._strip_meta(r) for r in results
            if not self._should_trim(r, token.roles, token.scopes)
        ]

    async def _authorize_execute(self, context, call_next, get_component: Callable, error_cls: type[FastMCPError]):
        try:
            token = get_access_token()
        except AuthError:
            raise error_cls("Access denied")

        component = await get_component(context)
        if self._should_trim(component, token.roles, token.scopes):
            raise error_cls("Access denied")

        return await call_next(context)

    def _should_trim(self, component: FastMCPComponent, roles: list[str], scopes: list[str]) -> bool:
        """Decide whether to hide a component from the caller.

        M2M tokens (CI pipelines) have scopes but no roles — they bypass role checks
        so all tools are available. User tokens must match required roles.
        """
        # M2M tokens have scopes but no roles — bypass role checks
        if scopes and not roles:
            return False
        meta = component.meta or {}
        if ROLES_META_KEY in meta and not any(r in roles for r in meta[ROLES_META_KEY]):
            return True
        if SCOPES_META_KEY in meta and not any(s in scopes for s in meta[SCOPES_META_KEY]):
            return True
        return False

    def _strip_meta(self, component: FastMCPComponent) -> FastMCPComponent:
        """Remove internal auth metadata (Roles/Scopes) before returning to caller."""
        meta = component.meta or {}
        if ROLES_META_KEY not in meta and SCOPES_META_KEY not in meta:
            return component
        c = copy.copy(component)
        c.meta = {k: v for k, v in meta.items() if k not in {ROLES_META_KEY, SCOPES_META_KEY}}
        return c

"""One confirm-token implementation, shared by the compound and granular servers.

A confirm token is the last barrier in front of a mutation that cannot be undone:
the first call mints a token and returns a preview *instead of acting*, and only a
second call carrying that token is allowed through. Tokens are short-lived,
single-use, bound to one action name, and bound to a fingerprint of the params, so
a token issued for one target set is refused when the targets change.

Tokens live in the process that issued them. The compound server and the granular
(`--full`) server are separate processes and therefore hold separate stores; a
token from one is not honoured by the other, which is what the CONFIRM_TOKEN_INVALID
message says out loud. Sharing this module shares the *implementation*, never the
state.

That distinction is the reason this file exists. Both servers reach
`TimelineItem.CopyGrades`, which replaces a target's whole node graph and leaves no
version to go back to, so both need the same gate — and a second hand-rolled copy of
it would drift from this one exactly the way seventeen copies of the live-harness
stub installer drifted before v4.1.3. The error builder differs between the two
surfaces (the compound server has a structured envelope, the granular server returns
plain dicts), so it is injected rather than assumed.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from typing import Any, Callable, Dict, Optional

#: Long enough for a human to read a preview and decide, short enough that a token
#: left lying around in a transcript is not a standing authorisation.
DEFAULT_TTL_SECONDS = 300


#: Preference key that switches the gate off, and the file both servers read it from.
PREFERENCE_KEY = "require_confirm_token"
PREFERENCE_SECTION = "destructive"

#: Both spellings a caller may hand the token back under. `consume` reads either,
#: and every gated action in the compound server treats either as "a token is
#: present", so `fingerprint` has to ignore both: a spelling the fingerprint does
#: not strip is an ordinary param, and the request looks different after issuance
#: than it did before.
TOKEN_PARAM_KEYS = ("confirm_token", "confirmToken")


def gate_required_from(preferences: Optional[Dict[str, Any]]) -> bool:
    """Read `destructive.require_confirm_token` out of a preferences payload.

    The policy — default on, and the exact set of strings that count as off — is
    shared even though each server reads the preferences file for itself, because
    the default is the part that must never drift. A surface that defaulted this to
    False would silently have no gate at all while still looking gated in code.
    """
    if not isinstance(preferences, dict):
        return True
    section = preferences.get(PREFERENCE_SECTION)
    if not isinstance(section, dict):
        return True
    value = section.get(PREFERENCE_KEY, True)
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return bool(value)


def plain_error(message: str, **fields: Any) -> Dict[str, Any]:
    """Error builder for surfaces with no structured envelope (the granular server).

    Keeps the diagnostic fields the confirm flow relies on — `code` above all, since
    that is what a caller branches on — without inventing an envelope the granular
    tools do not otherwise emit.
    """
    body: Dict[str, Any] = {"success": False, "error": message}
    for key, value in fields.items():
        if value is not None:
            body[key] = value
    return body


class ConfirmTokenStore:
    """Mint, hold and redeem one-time confirmation tokens.

    `required` and `err` are callables rather than values so that a caller can swap
    either at runtime: the compound server's preference lookup is patched by tests
    on the module object, and resolving it per call is what makes that patch visible
    here instead of being captured once at construction.
    """

    def __init__(
        self,
        *,
        err: Callable[..., Dict[str, Any]],
        required: Optional[Callable[[], bool]] = None,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> None:
        self._err = err
        self._required = required if required is not None else (lambda: True)
        self.ttl_seconds = ttl_seconds
        self.tokens: Dict[str, Dict[str, Any]] = {}
        # The control panel runs on a threaded HTTP server, so issue/consume/gc can
        # run on concurrent threads. Guard every access so a GC pass cannot race a
        # write and so validate-then-pop stays atomic.
        self.lock = threading.RLock()

    # ── internals ────────────────────────────────────────────────────────────

    def required(self) -> bool:
        """Is the gate switched on right now?"""
        return bool(self._required())

    def fingerprint(self, action: str, params: Optional[Dict[str, Any]]) -> str:
        """Stable hash of (action, params) identifying one specific mutation request."""
        payload = {"action": action, "params": params or {}}
        # Strip the token itself if the caller is echoing it back to us, so the
        # fingerprint of "the request" is the same before and after issuance.
        # Both spellings, not just the snake_case one: `consume` accepts either.
        if isinstance(payload["params"], dict):
            payload["params"] = {
                k: v for k, v in payload["params"].items() if k not in TOKEN_PARAM_KEYS
            }
        try:
            blob = json.dumps(payload, sort_keys=True, default=str)
        except Exception:
            blob = repr(payload)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

    def gc(self) -> None:
        """Drop expired tokens. Callers may already hold the lock; RLock re-entry is safe."""
        now = time.time()
        with self.lock:
            expired = [t for t, rec in self.tokens.items() if rec.get("expires_at", 0) < now]
            for token in expired:
                self.tokens.pop(token, None)

    # ── the gate ─────────────────────────────────────────────────────────────

    def issue(
        self,
        *,
        action: str,
        params: Optional[Dict[str, Any]],
        preview: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Mint a token and return the pending_user_decision response shape."""
        token = uuid.uuid4().hex
        expires_at = time.time() + self.ttl_seconds
        with self.lock:
            self.gc()
            self.tokens[token] = {
                "action": action,
                "fingerprint": self.fingerprint(action, params),
                "expires_at": expires_at,
                "issued_at": time.time(),
            }
        body = self._err(
            "This action is destructive. Re-call with confirm_token to proceed.",
            code="CONFIRMATION_REQUIRED",
            category="pending_user_decision",
            retryable=False,
            remediation=(
                f"Re-call {action} with params.confirm_token={token!r}; "
                f"token expires in {self.ttl_seconds}s."
            ),
        )
        body.update({
            "status": "confirmation_required",
            "confirm_token": token,
            "preview": preview,
            "expires_at_epoch": expires_at,
            "ttl_seconds": self.ttl_seconds,
        })
        return body

    def consume(
        self,
        *,
        action: str,
        params: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Redeem a token.

        Returns None when the call may proceed — which covers three distinct cases:
        gating is switched off, no token was supplied (the caller is expected to
        call `issue` in that case), or the token was valid and has now been spent.
        Returns an error body when a token was supplied but is not good.
        """
        if not self.required():
            return None
        supplied = params or {}
        token = next((supplied.get(key) for key in TOKEN_PARAM_KEYS if supplied.get(key)), None)
        if not token:
            return None  # Caller is expected to call issue() in this case.
        with self.lock:
            self.gc()
            rec = self.tokens.pop(token, None)  # one-time use, atomic with gc
        if rec is None:
            return self._err(
                "confirm_token is invalid, expired, or was issued by a different "
                "server instance (tokens are valid only on the instance that "
                "issued them — e.g. a stdio-server token is not honored by the "
                "networked server).",
                code="CONFIRM_TOKEN_INVALID",
                category="destructive_blocked",
                retryable=False,
                remediation=(
                    f"Re-call {action} without confirm_token on this instance to "
                    "receive a fresh token."
                ),
            )
        if rec.get("action") != action:
            return self._err(
                f"confirm_token issued for {rec.get('action')!r}, not {action!r}",
                code="CONFIRM_TOKEN_ACTION_MISMATCH",
                category="destructive_blocked",
                retryable=False,
            )
        if rec.get("fingerprint") != self.fingerprint(action, params):
            return self._err(
                "confirm_token does not match the current params",
                code="CONFIRM_TOKEN_FINGERPRINT_MISMATCH",
                category="destructive_blocked",
                retryable=False,
                remediation=(
                    "Either re-issue the token with current params or roll back "
                    "the params change."
                ),
            )
        return None  # OK to proceed

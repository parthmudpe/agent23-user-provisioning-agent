"""Strict input validation. Everything from the LLM is untrusted."""
import re

USERNAME_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
COMMENT_RE = re.compile(r"^[\w .'@-]{0,64}$")
PATH_PART_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
MODE_RE = re.compile(r"^[0-7]{3,4}$")


class ValidationError(ValueError):
    """Raised when an input fails validation."""


def validate_username(name):
    if not isinstance(name, str) or not USERNAME_RE.fullmatch(name):
        raise ValidationError(
            f"Invalid username {name!r}: use 1-32 chars, lowercase letters, digits, "
            "'_' or '-', starting with a letter or '_'.")
    return name


def validate_groupname(name):
    if not isinstance(name, str) or not USERNAME_RE.fullmatch(name):
        raise ValidationError(
            f"Invalid group name {name!r}: use 1-32 chars, lowercase letters, digits, "
            "'_' or '-', starting with a letter or '_'.")
    return name


def validate_group_list(groups, limit=16):
    if groups is None:
        return []
    if not isinstance(groups, list) or len(groups) > limit:
        raise ValidationError(f"'groups' must be a list of at most {limit} names.")
    seen, out = set(), []
    for g in groups:
        g = validate_groupname(g)
        if g not in seen:
            seen.add(g)
            out.append(g)
    return out


def validate_comment(comment):
    comment = "" if comment is None else comment
    if not isinstance(comment, str) or not COMMENT_RE.fullmatch(comment):
        raise ValidationError(
            "Invalid comment/full name: max 64 chars of letters, digits, space, "
            "'.', ''', '@', '-', '_' (no ':' ',' or control characters).")
    return comment


def validate_gid(gid):
    if gid is None:
        return None
    if isinstance(gid, bool) or not isinstance(gid, int) or not 1000 <= gid <= 60000:
        raise ValidationError("gid must be an integer between 1000 and 60000.")
    return gid


def validate_shell(shell, allowed):
    if not isinstance(shell, str) or shell not in allowed:
        raise ValidationError(
            f"Shell {shell!r} is not listed in /etc/shells. Allowed: {sorted(allowed)}")
    return shell


def validate_mode(mode):
    mode = "700" if mode is None else str(mode)
    if not MODE_RE.fullmatch(mode):
        raise ValidationError("mode must be 3-4 octal digits, e.g. '700' or '750'.")
    value = int(mode, 8)
    if value & 0o7000:
        raise ValidationError("setuid/setgid/sticky bits are not allowed.")
    if value & 0o002:
        raise ValidationError("world-writable modes are not allowed.")
    return mode


def validate_relpath(rel):
    """Return path components of a safe path relative to a user's home."""
    if not isinstance(rel, str) or not rel or len(rel) > 200:
        raise ValidationError("relative_path must be a non-empty string (max 200 chars).")
    if rel.startswith("/"):
        raise ValidationError("relative_path must be relative to the user's home.")
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    if not parts or len(parts) > 8:
        raise ValidationError("relative_path must have 1-8 components.")
    for p in parts:
        if not PATH_PART_RE.fullmatch(p):
            raise ValidationError(f"Illegal path component {p!r} ('..', spaces and symbols are rejected).")
    return parts

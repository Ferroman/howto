"""Errors that end a command, each with the exit code the design assigns it."""


class HowtoError(Exception):
    exit_code = 1


class StoryboardError(HowtoError):
    """The storyboard file or the command line is wrong."""

    exit_code = 2


class RunError(HowtoError):
    """A step, the narration or the assembly failed."""

    exit_code = 1

"""Sandboxed file-management tools.

All file operations are restricted to ``root_dir`` via LangChain's
:class:`FileManagementToolkit`.  The toolkit resolves every path relative
to the root and rejects traversals that escape it.
"""

from __future__ import annotations

import os

from langchain_community.agent_toolkits import FileManagementToolkit
from langchain_core.tools import BaseTool


def get_file_tools(workspace_dir: str = "/app/workspace") -> list[BaseTool]:
    """Return file-management tools sandboxed to *workspace_dir*.

    The directory is created if it does not exist.  The returned list
    contains: CopyFile, DeleteFile, FileSearch, MoveFile, ReadFile,
    WriteFile, and ListDirectory -- all confined to *workspace_dir*.
    """
    os.makedirs(workspace_dir, exist_ok=True)

    toolkit = FileManagementToolkit(root_dir=workspace_dir)
    return toolkit.get_tools()

"""Tool schemas + tool-calling tasks (BFCL-style, but authored fresh)."""

READ_FILE = {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "Read a UTF-8 text file from the repository.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Repo-relative path, e.g. src/app.py"}},
            "required": ["path"],
        },
    },
}

WRITE_FILE = {
    "type": "function",
    "function": {
        "name": "write_file",
        "description": "Overwrite a file with new content. Creates parent directories.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Repo-relative path"},
                "content": {"type": "string", "description": "Full new file content"},
            },
            "required": ["path", "content"],
        },
    },
}

LIST_FILES = {
    "type": "function",
    "function": {
        "name": "list_files",
        "description": "List files under a directory in the repository.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Directory, default '.'"}},
        },
    },
}

SEARCH_CODE = {
    "type": "function",
    "function": {
        "name": "search_code",
        "description": "Semantic search over indexed symbols and docstrings. Use for concepts, e.g. 'where is auth handled'. Does not match raw text.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural-language description"},
                "limit": {"type": "integer", "description": "Max results, default 10"},
            },
            "required": ["query"],
        },
    },
}

GREP_FILES = {
    "type": "function",
    "function": {
        "name": "grep_files",
        "description": "Literal substring or regex search across file contents. Use for exact identifiers and strings.",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Literal string or regex"},
                "glob": {"type": "string", "description": "File glob, default '**/*'"},
            },
            "required": ["pattern"],
        },
    },
}

FIND_FILES = {
    "type": "function",
    "function": {
        "name": "find_files",
        "description": "Find files by name or glob. Does not look inside file contents.",
        "parameters": {
            "type": "object",
            "properties": {"glob": {"type": "string", "description": "e.g. '**/*.test.ts'"}},
            "required": ["glob"],
        },
    },
}

RUN_TESTS = {
    "type": "function",
    "function": {
        "name": "run_tests",
        "description": "Run the project test suite, optionally filtered to one file.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Optional test file path"}},
        },
    },
}

CREATE_ISSUE = {
    "type": "function",
    "function": {
        "name": "create_issue",
        "description": "Open a tracked issue.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "priority": {"type": "string", "enum": ["low", "medium", "high"]},
                "labels": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["title", "priority"],
        },
    },
}

GET_WEATHER = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Current weather for a city.",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    },
}

RUN_COMMAND = {
    "type": "function",
    "function": {
        "name": "run_command",
        "description": "Run a PowerShell command in the workspace directory. Use it to run scripts and tests.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "PowerShell command, e.g. python verify.py"}
            },
            "required": ["command"],
        },
    },
}

FINISH = {
    "type": "function",
    "function": {
        "name": "finish",
        "description": "Call when the task is complete and verification passes.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}

TOOLS = {
    "read_file": READ_FILE,
    "write_file": WRITE_FILE,
    "list_files": LIST_FILES,
    "search_code": SEARCH_CODE,
    "grep_files": GREP_FILES,
    "find_files": FIND_FILES,
    "run_tests": RUN_TESTS,
    "create_issue": CREATE_ISSUE,
    "get_weather": GET_WEATHER,
    "run_command": RUN_COMMAND,
    "finish": FINISH,
}

TASKS = [
    {
        "id": "tc-01",
        "category": "toolcalls",
        "title": "single call, obvious path",
        "difficulty": "easy",
        "mode": "tools",
        "no_think": True,
        "prompt": "Show me what is inside src/app.py.",
        "tools": ["read_file", "list_files", "run_tests"],
        "expect": {"name": "read_file", "args": {"path": "src/app.py"}},
    },
    {
        "id": "tc-02",
        "category": "toolcalls",
        "title": "write vs read disambiguation",
        "difficulty": "easy",
        "mode": "tools",
        "no_think": True,
        "prompt": "Replace the contents of config.yaml with exactly:\n\ndebug: true\nverbose: false\n",
        "tools": ["read_file", "write_file", "list_files"],
        "expect": {"name": "write_file", "args": {"path": "config.yaml", "content": "debug: true"}},
    },
    {
        "id": "tc-03",
        "category": "toolcalls",
        "title": "two parallel calls",
        "difficulty": "medium",
        "mode": "tools",
        "no_think": True,
        "prompt": "Read both src/a.py and src/b.py and tell me which one is longer.",
        "tools": ["read_file", "list_files"],
        "expect": {"calls": [
            {"name": "read_file", "args": {"path": "src/a.py"}},
            {"name": "read_file", "args": {"path": "src/b.py"}},
        ]},
    },
    {
        "id": "tc-04",
        "category": "toolcalls",
        "title": "typed + enum + array args",
        "difficulty": "medium",
        "mode": "tools",
        "no_think": True,
        "prompt": "Open a high priority issue titled 'Login fails on Safari' with the labels 'bug' and 'auth'.",
        "tools": ["create_issue", "search_code"],
        "expect": {
            "name": "create_issue",
            "args": {"title": "Login fails on Safari", "priority": "high", "labels": ["bug", "auth"]},
        },
    },
    {
        "id": "tc-05",
        "category": "toolcalls",
        "title": "irrelevance: no tool needed",
        "difficulty": "medium",
        "mode": "tools",
        "no_think": True,
        "prompt": "What is 17 * 23? Answer with the number only.",
        "tools": ["read_file", "search_code", "run_tests", "get_weather"],
        "expect": {"no_tool": True, "contains": ["391"]},
    },
    {
        "id": "tc-06",
        "category": "toolcalls",
        "title": "missing argument: ask, don't guess",
        "difficulty": "medium",
        "mode": "tools",
        "no_think": True,
        "prompt": "Search the codebase.",
        "tools": ["search_code", "grep_files", "read_file"],
        "expect": {"ask": True},
    },
    {
        "id": "tc-07",
        "category": "toolcalls",
        "title": "multi-turn: consume tool result",
        "difficulty": "medium",
        "mode": "tools",
        "no_think": True,
        "prompt": "Find every TODO comment in the repo and tell me which file has the most.",
        "tools": ["grep_files", "read_file", "list_files"],
        "expect": {"name": "grep_files", "args": {"pattern": "TODO"}},
        "followup": {
            "result": "steering.py: 4 matches\nrouter.py: 1 match\nutils.py: 0 matches",
            "contains": ["steering.py"],
            "no_more_calls": True,
        },
        "max_tokens": 500,
    },
    {
        "id": "tc-08",
        "category": "toolcalls",
        "title": "overlapping tools: literal vs semantic vs glob",
        "difficulty": "hard",
        "mode": "tools",
        "no_think": True,
        "prompt": "Find every occurrence of the literal string 'MAX_RETRIES' anywhere in the repository.",
        "tools": ["search_code", "grep_files", "find_files"],
        "expect": {"name": "grep_files", "args": {"pattern": "MAX_RETRIES"}},
    },
]

from pydantic import BaseModel, ConfigDict, Field

class Crash(BaseModel):
    model_config = ConfigDict(extra="forbid")  # emits "additionalProperties": false in the JSON schema

    file: str = Field(..., description="File where the crash happened, with a suffix of : and a line number", examples=["src/audio/AudioMixer.cpp:10"])
    stacktrace: list[str] = Field(..., description="Array of strings for the stack trace, with the function and in parenthesis the file and the line.", examples=[[
        "AudioMixer::playSound (src/audio/AudioMixer.cpp:10)",
        "Player::attack (src/gameplay/Player.cpp:22)",
        "Game::tick (src/core/Game.cpp:27)",
        "Game::run (src/core/Game.cpp:38)",
        "main (src/main.cpp:5)"
    ]])
    assigned_team: str = Field(..., description="Team name that needs to fix it")

class OutputCrash(Crash):
    priority: int = Field(..., ge=1, le=10, description="Number from 1 to 10 of the priority")

class DAG_NODE(BaseModel):
    model_config = ConfigDict(extra="forbid")  # emits "additionalProperties": false in the JSON schema

    id: str = Field (..., description="A dollar and the order of the tool. Example: $1")
    tool_name: str = Field (..., description="Name of the tool to execute"),
    tool_args: list[str] = Field (..., description="List of arguments for that tool input. If it's unresolved because it needs previous tools, use the id ($1, $2, ...)")

class DAG(BaseModel):
    model_config = ConfigDict(extra="forbid")  # emits "additionalProperties": false in the JSON schema

    nodes: list[DAG_NODE] = Field (..., description="An array of nodes with id, tool_name, tool_args, etc. Already encodes dependencies by using as tool_args a reference to a previous tool if neede by id ($1...)")


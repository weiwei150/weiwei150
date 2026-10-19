import configparser
import subprocess

from openai import OpenAI

config = configparser.ConfigParser()
config.read("config.ini", encoding="utf-8")

base_url = config["llm"]["base_url"]
model_name = config["llm"]["model_name"]
api_key = config["llm"]["api_key"]

client = OpenAI(base_url=base_url, api_key=api_key)

tools = [
    {
        "type": "function",
        "function": {
            "name": "getDate",
            "description": "获取当前电脑的日期和时间，通过调用本地 date/time 命令实现",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    }
]


def get_date() -> str:
    result = subprocess.run(
        "date /t & time /t",
        shell=True,
        capture_output=True,
        text=True,
    )
    output = result.stdout.strip()
    return output


def handle_tool_calls(tool_calls) -> list:
    messages = []
    for tool_call in tool_calls:
        function = tool_call["function"]
        name = function["name"]
        print(f"[工具调用] {name}({function['arguments']})")

        if name == "getDate":
            content = get_date()
        else:
            content = f"未知工具: {name}"

        print(f"[工具结果] {content}")
        print("---")

        messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "content": content,
            }
        )
    return messages


messages = []

while True:
    try:
        prompt = input("请输入提示词: ")

        print("---")

        messages.append({"role": "user", "content": prompt})

        while True:
            stream = client.chat.completions.create(
                model=model_name,
                messages=messages,
                tools=tools,
                stream=True,
            )

            reply = ""
            pending_tool_calls = {}

            for chunk in stream:
                if not chunk.choices:
                    continue

                delta = chunk.choices[0].delta
                if delta is None:
                    continue

                if delta.content:
                    reply += delta.content
                    print(delta.content, end="", flush=True)

                for tc in delta.tool_calls or []:
                    slot = pending_tool_calls.setdefault(
                        tc.index, {"id": "", "name": "", "arguments": ""}
                    )
                    if tc.id:
                        slot["id"] = tc.id
                    if tc.function and tc.function.name:
                        slot["name"] = tc.function.name
                    if tc.function and tc.function.arguments:
                        slot["arguments"] += tc.function.arguments

            if not pending_tool_calls:
                print()
                if reply:
                    messages.append({"role": "assistant", "content": reply})
                break

            print()

            tool_calls = [
                {
                    "id": pending_tool_calls[index]["id"],
                    "type": "function",
                    "function": {
                        "name": pending_tool_calls[index]["name"],
                        "arguments": pending_tool_calls[index]["arguments"],
                    },
                }
                for index in sorted(pending_tool_calls)
            ]

            messages.append(
                {
                    "role": "assistant",
                    "content": reply or None,
                    "tool_calls": tool_calls,
                }
            )

            messages.extend(handle_tool_calls(tool_calls))
    except (KeyboardInterrupt, EOFError):
        break

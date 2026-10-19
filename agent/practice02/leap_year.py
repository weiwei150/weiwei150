import configparser
import json

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
            "name": "isLeapYear",
            "description": "计算输入的年份是否是闰年",
            "parameters": {
                "type": "object",
                "properties": {
                    "year": {
                        "type": "integer",
                        "description": "待判断的年份，例如 2024",
                    }
                },
                "required": ["year"],
            },
        },
    }
]


def is_leap_year(year: int) -> bool:
    return (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)


def handle_tool_calls(tool_calls) -> list:
    messages = []
    for tool_call in tool_calls:
        function = tool_call["function"]
        name = function["name"]
        print(f"[工具调用] {name}({function['arguments']})")

        if name == "isLeapYear":
            arguments = json.loads(function["arguments"])
            year = int(arguments["year"])
            result = is_leap_year(year)
            content = f"{year}年{'是' if result else '不是'}闰年"
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

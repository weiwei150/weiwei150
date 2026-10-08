import configparser

from openai import OpenAI

config = configparser.ConfigParser()
config.read("config.ini", encoding="utf-8")

base_url = config["llm"]["base_url"]
model_name = config["llm"]["model_name"]
api_key = config["llm"]["api_key"]

client = OpenAI(base_url=base_url, api_key=api_key)

messages = []
while True:
    try:
        prompt = input("请输入提示词: ")
        if not prompt:
            continue
        messages.append({"role": "user", "content": prompt})
        print("---")
        stream = client.chat.completions.create(
            model=model_name,
            messages=messages,
            stream=True,
        )
        response_content = ""
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                content = chunk.choices[0].delta.content
                print(content, end="", flush=True)
                response_content += content
        print()
        messages.append({"role": "assistant", "content": response_content})
    except KeyboardInterrupt:
        break

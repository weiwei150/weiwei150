import configparser

from openai import OpenAI

config = configparser.ConfigParser()
config.read("config.ini", encoding="utf-8")

base_url = config["llm"]["base_url"]
model_name = config["llm"]["model_name"]
api_key = config["llm"]["api_key"]

prompt = input("请输入提示词: ")

print("---")

client = OpenAI(base_url=base_url, api_key=api_key)

stream = client.chat.completions.create(
    model=model_name,
    messages=[{"role": "user", "content": prompt}],
    stream=True,
)

for chunk in stream:
    if chunk.choices and chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="", flush=True)

print()
